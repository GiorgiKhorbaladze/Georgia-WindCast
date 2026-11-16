"""Durable store, scheduled collector and history reader (offline, recorded GSE payloads)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import httpx
import pytest
from collector import Collector, due_labels
from history import HistoryReader, collector_age
from store import Record, StoreFormatError, day_path, merge, parse_day_csv, render_day_csv

ROOT = Path(__file__).resolve().parents[2]
ACT = (ROOT / "backend/tests/fixtures/gse/real_act_15112026_0009.xml").read_bytes()
NAME = re.compile(r"_(\d\d)(\d\d)(\d{4})_(\d\d)(\d\d)\.XML$")
NOW = datetime(2026, 11, 14, 20, 20, tzinfo=UTC)
TBILISI = ZoneInfo("Asia/Tbilisi")  # newest due label 20:18 UTC (00:18 Tbilisi)


def relabel(local: str, base: bytes = ACT) -> bytes:
    return base.replace(b"Time='15.11.2026 00:09:00'", f"Time='{local}'".encode(), 1)


class Gse:
    """Serves the recorded file relabelled to each requested period; some periods 404."""

    def __init__(self, missing=(), override=None):
        self.missing, self.override, self.requests = set(missing), override, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        self.requests.append(name)
        dd, mm, yyyy, hh, mi = NAME.search(name).groups()
        if self.override:
            return self.override(name)
        if f"{hh}:{mi}" in self.missing:
            return httpx.Response(404, headers={"content-type": "text/html"})
        body = relabel(f"{dd}.{mm}.{yyyy} {hh}:{mi}:00")
        return httpx.Response(200, content=body, headers={"content-type": "text/xml"})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def collector(tmp_path, gse, **kw):
    kw.setdefault("deep_per_run", 0)  # steady-state behaviour; deep backfill has its own tests
    return Collector(tmp_path, gse.client, lookback_hours=kw.pop("hours", 1), **kw)


def rec(minute: int, sha: str = "a", quality: str = "ACT") -> Record:
    return Record(datetime(2026, 11, 14, 20, minute, tzinfo=UTC), "x", 1.5, quality, NOW, sha, "p")


# ------------------------------------------------------------------------------------- store

def test_csv_round_trip_and_strict_format():
    rows = [rec(9), rec(3, quality="NRE")]
    text = render_day_csv(rows)
    assert parse_day_csv(text) == sorted(rows, key=lambda r: r.period_label_utc)
    with pytest.raises(StoreFormatError):
        parse_day_csv(text.replace("period_label_utc", "label", 1))
    with pytest.raises(StoreFormatError):
        parse_day_csv(text + text.splitlines()[1] + "\n")  # duplicate label
    with pytest.raises(StoreFormatError):
        parse_day_csv(text.replace("+00:00", "", 1))  # naive timestamp


def test_merge_is_idempotent_and_counts_revisions():
    rows, outcome = merge([], rec(9))
    assert outcome == "inserted"
    assert merge(rows, rec(9))[1] == "unchanged"
    revised, outcome = merge(rows, rec(9, sha="b"))
    assert outcome == "revised" and revised[0].revision == 1 and revised[0].payload_sha256 == "b"


def test_day_path_uses_utc_label_date():
    assert day_path(datetime(2026, 11, 14, 23, 57, tzinfo=UTC).date()) == "gse/2026/11/2026-11-14.csv"


# --------------------------------------------------------------------------------- collector

def test_collector_backfills_lookback_and_keeps_gaps(tmp_path):
    gse = Gse(missing={"00:12"})
    report, code = collector(tmp_path, gse).run(NOW)
    assert code == 0 and report.requested == 20 and report.inserted == 19 and report.not_published == 1
    rows = parse_day_csv((tmp_path / "gse/2026/11/2026-11-14.csv").read_text())
    labels = [r.period_label_utc for r in rows]
    assert datetime(2026, 11, 14, 20, 12, tzinfo=UTC) not in labels  # gap stays a gap
    assert labels[-1] == datetime(2026, 11, 14, 20, 18, tzinfo=UTC)
    assert all(r.value_mw == pytest.approx(73.599297) and r.quality == "ACT" for r in rows)
    status = json.loads((tmp_path / "status/gse_collector.json").read_text())
    assert status["latest_label_utc"] == "2026-11-14T20:18:00+00:00"
    assert status["last_success_at"] == NOW.isoformat()


def test_second_run_requests_only_missing_and_abandons_holes(tmp_path):
    gse = Gse(missing={"00:12"})
    collector(tmp_path, gse).run(NOW)
    for i in range(1, 6):
        gse.requests.clear()
        report, _ = collector(tmp_path, gse).run(NOW + timedelta(seconds=10 * i))
        expected = 1 if i < 4 else 0  # 4 attempts in total, then the hole is left alone
        assert report.requested == expected, (i, gse.requests)


def test_irregular_schedule_does_not_create_gaps(tmp_path):
    gse = Gse()
    collector(tmp_path, gse, hours=12).run(NOW)
    collector(tmp_path, gse, hours=12).run(NOW + timedelta(hours=5))  # GitHub skipped runs for 5 h
    labels = set()
    for day in ("2026-11-14", "2026-11-15"):
        path = tmp_path / f"gse/2026/11/{day}.csv"
        if path.exists():
            labels |= {r.period_label_utc for r in parse_day_csv(path.read_text())}
    expected = set(due_labels(NOW + timedelta(hours=5), 5)) | set(due_labels(NOW, 12))
    assert expected <= labels


def test_mislabelled_file_is_refused_and_fails_visibly(tmp_path):
    gse = Gse(override=lambda name: httpx.Response(200, content=relabel("14.11.2026 23:00:00"),
                                                   headers={"content-type": "text/xml"}))
    report, code = collector(tmp_path, gse).run(NOW)
    assert code == 1 and report.inserted == 0 and report.integrity_error.startswith("parse_error")
    assert not (tmp_path / "gse").exists()


def test_html_200_is_never_data_and_outage_alerts_only_when_stale(tmp_path):
    html = Gse(override=lambda name: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}))
    report, code = collector(tmp_path, html).run(NOW)
    assert report.failures == 20 and code == 2  # nothing stored at all yet: alert
    collector(tmp_path, Gse()).run(NOW)
    _, code = collector(tmp_path, html).run(NOW + timedelta(minutes=30))
    assert code == 0  # transient: the latest reading is recent


def test_schema_drift_is_refused(tmp_path):
    bad = Gse(override=lambda name: httpx.Response(200, content=b"<GSE><x/></GSE>", headers={"content-type": "text/xml"}))
    _, code = collector(tmp_path, bad).run(NOW)
    assert code == 1


# ----------------------------------------------------------------------------- history reader

def reader_for(tmp_path, counter=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.append(request.url.path)
        path = tmp_path / request.url.path.split("/data/", 1)[1]
        return httpx.Response(200, content=path.read_bytes()) if path.exists() else httpx.Response(404)
    return HistoryReader(lambda: httpx.Client(transport=httpx.MockTransport(handler)), "https://example.test/data/")


@pytest.mark.real_history
def test_reader_returns_collected_rows_and_caches(tmp_path):
    collector(tmp_path, Gse()).run(NOW)
    calls = []
    reader = reader_for(tmp_path, calls)
    rows = reader.records(NOW - timedelta(hours=1), NOW, NOW)
    assert len(rows) == 20 and rows[-1].period_label_utc == datetime(2026, 11, 14, 20, 18, tzinfo=UTC)
    n = len(calls)
    reader.records(NOW - timedelta(hours=1), NOW, NOW + timedelta(seconds=30))
    assert len(calls) == n  # cached
    status = reader.status(NOW)
    assert collector_age(status, NOW + timedelta(minutes=5)) == timedelta(minutes=5)


@pytest.mark.real_history
def test_reader_keeps_last_good_copy_on_errors(tmp_path):
    collector(tmp_path, Gse()).run(NOW)
    reader = reader_for(tmp_path)
    first = reader.records(NOW - timedelta(hours=1), NOW, NOW)
    reader._client_factory = lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    again = reader.records(NOW - timedelta(hours=1), NOW, NOW + timedelta(minutes=5))
    assert again == first and reader.error == "history_unavailable"


@pytest.mark.real_history
def test_reader_missing_day_is_empty_not_error(tmp_path):
    reader = reader_for(tmp_path)
    assert reader.records(NOW - timedelta(days=3), NOW, NOW) == [] and reader.error is None
    assert reader.status(NOW) is None and collector_age(None, NOW) is None


# ---------------------------------------------------------------- Open-Meteo copies (second path)

FIX = ROOT / "backend/tests/fixtures/openmeteo"
FORECAST_BODY = (FIX / "real_forecast_icon_global_3sites.json").read_bytes()
ARCHIVE_BODY = (FIX / "real_archive_era5_3sites_20261106.json").read_bytes()
META = (FIX / "real_meta_dwd_icon_before.json").read_bytes()  # run 2026-11-14T18:00Z
RUN = datetime(2026, 11, 14, 18, tzinfo=UTC)


class Weather:
    def __init__(self, metas=None, forecast=FORECAST_BODY, status=200):
        self.metas, self.forecast, self.status, self.calls = list(metas or [META]), forecast, status, []

    def handler(self, request):
        self.calls.append(request.url.path)
        if self.status != 200:
            return httpx.Response(self.status, headers={"content-type": "application/json"}, content=b"{}")
        if request.url.path.endswith("meta.json"):
            body = self.metas.pop(0) if len(self.metas) > 1 else self.metas[0]
            return httpx.Response(200, content=body, headers={"content-type": "application/json"})
        body = self.forecast if request.url.path == "/v1/forecast" else ARCHIVE_BODY
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_weather_copies_stored_once_per_run_and_day(tmp_path):
    from collector import collect_weather
    w = Weather()
    status, code = collect_weather(tmp_path, w.client, RUN + timedelta(hours=1))
    assert code == 0 and status == {**status, "forecast": "updated", "era5": "updated"}
    assert (tmp_path / "weather/forecast.json").read_bytes() == FORECAST_BODY
    meta = json.loads((tmp_path / "weather/forecast_meta.json").read_text())
    assert meta["run"] == RUN.isoformat()
    w.calls.clear()
    status, _ = collect_weather(tmp_path, w.client, RUN + timedelta(hours=2))
    assert status["forecast"] == "unchanged" and status["era5"] == "unchanged"
    assert w.calls == ["/data/dwd_icon/static/meta.json"]  # only the run check


def test_weather_run_change_and_rate_limit_keep_old_copy(tmp_path):
    from collector import collect_weather
    newer = json.dumps({"last_run_initialisation_time": int(RUN.timestamp()) + 6 * 3600}).encode()
    status, code = collect_weather(tmp_path, Weather(metas=[META, newer]).client, RUN + timedelta(hours=7))
    assert status["forecast"] == "failed: model_run_changed_during_fetch" and code == 0
    assert not (tmp_path / "weather/forecast.json").exists()
    status, code = collect_weather(tmp_path, Weather(status=429).client, RUN + timedelta(hours=7))
    assert status["forecast"] == "failed: rate_limited" and code == 0


def test_weather_schema_drift_is_refused(tmp_path):
    from collector import collect_weather
    status, code = collect_weather(tmp_path, Weather(forecast=b'{"hourly": {}}').client, RUN + timedelta(hours=1))
    assert status["forecast"].startswith("refused") and code == 1
    assert not (tmp_path / "weather/forecast.json").exists()


@pytest.mark.real_history
def test_reader_serves_stored_weather_and_cache_prefers_newer_run(tmp_path):
    from collector import collect_weather
    from data import SourceCache
    collect_weather(tmp_path, Weather().client, RUN + timedelta(hours=1))
    forecast, archive = reader_for(tmp_path).weather(RUN + timedelta(hours=1))
    assert forecast["run"] == RUN and forecast["origin"] == "collector" and len(forecast["series"]) == 3
    assert archive["origin"] == "collector"
    cache = SourceCache()
    older = dict(forecast, run=RUN - timedelta(hours=6), origin="live")
    cache.forecast = older
    cache.adopt_stored(forecast, archive)
    assert cache.forecast["run"] == RUN and cache.archive is archive
    cache.adopt_stored(dict(forecast, run=RUN - timedelta(hours=12)), None)
    assert cache.forecast["run"] == RUN  # never replaced by an older run


def test_all_404_outage_and_recovery(tmp_path):
    missing = Gse(override=lambda name: httpx.Response(404))
    report, code = collector(tmp_path, missing).run(NOW)
    assert code == 2 and report.not_published == 20
    status = json.loads((tmp_path / 'status/gse_collector.json').read_text())
    assert 'last_success_at' not in status
    collector(tmp_path, Gse()).run(NOW)
    assert collector(tmp_path, missing).run(NOW + timedelta(minutes=15))[1] == 0
    assert collector(tmp_path, missing).run(NOW + timedelta(hours=7))[1] == 2
    status = json.loads((tmp_path / 'status/gse_collector.json').read_text())
    assert status['last_success_at'] == NOW.isoformat()
    assert collector(tmp_path, Gse()).run(NOW + timedelta(hours=7))[1] == 0


def test_collector_rediscovers_revisions_and_bounds_requests(tmp_path):
    from dataclasses import replace
    collector(tmp_path, Gse()).run(NOW)
    path = tmp_path / day_path(NOW.date())
    rows = parse_day_csv(path.read_text())
    label = rows[-1].period_label_utc
    rows[-1] = replace(rows[-1], quality='NRE', value_mw=0, payload_sha256='old')
    path.write_text(render_day_csv(rows))
    later = NOW + timedelta(hours=1)
    report, code = collector(tmp_path, Gse(), hours=3, max_requests=40).run(later)
    assert code == 0 and report.revised == 1 and report.requested <= 40
    revised = next(r for r in parse_day_csv(path.read_text()) if r.period_label_utc == label)
    assert revised.quality == 'ACT' and revised.value_mw > 0 and revised.revision == 1
    collector(tmp_path, Gse(), hours=4, max_requests=80).run(later + timedelta(hours=1))
    assert next(r for r in parse_day_csv(path.read_text()) if r.period_label_utc == label).revision == 1


@pytest.mark.real_history
@pytest.mark.parametrize('product', ['forecast', 'era5'])
@pytest.mark.parametrize('fault', ['hash', 'naive', 'future', 'missing'])
def test_stored_weather_refuses_bad_copy_retains_and_recovers(tmp_path, product, fault):
    from collector import collect_weather
    now = RUN + timedelta(hours=1)
    collect_weather(tmp_path, Weather().client, now)
    reader = reader_for(tmp_path)
    first = reader.weather(now)
    meta_path = tmp_path / f'weather/{product}_meta.json'
    original = meta_path.read_text()
    meta = json.loads(original)
    if fault == 'hash':
        # Legacy mutable URL rollover: metadata hash must reject a different valid JSON body.
        meta.pop('content_addressed')
        payload = tmp_path / f'weather/{product}.json'
        payload.write_bytes(payload.read_bytes() + b' ')
    elif fault == 'naive':
        meta['retrieved'] = now.replace(tzinfo=None).isoformat()
    elif fault == 'future':
        meta['retrieved'] = (now + timedelta(days=1)).isoformat()
    if fault == 'missing':
        meta_path.unlink()
    else:
        meta_path.write_text(json.dumps(meta))
    index = 0 if product == 'forecast' else 1
    assert reader.weather(now + timedelta(minutes=11))[index] is first[index]
    # A fresh reader must never adopt this unvalidated copy.
    assert reader_for(tmp_path).weather(now + timedelta(minutes=11))[index] is None
    meta_path.write_text(original)
    assert reader.weather(now + timedelta(minutes=22))[index]['sha256'] == first[index]['sha256']


@pytest.mark.real_history
@pytest.mark.parametrize('run', ['2026-11-14T18:00:00', '2026-11-15T18:00:00+00:00'])
def test_stored_forecast_refuses_invalid_run(tmp_path, run):
    from collector import collect_weather
    now = RUN + timedelta(hours=1)
    collect_weather(tmp_path, Weather().client, now)
    path = tmp_path / 'weather/forecast_meta.json'
    meta = json.loads(path.read_text())
    meta['run'] = run
    path.write_text(json.dumps(meta))
    forecast, archive = reader_for(tmp_path).weather(now)
    assert forecast is None and archive is not None


@pytest.mark.real_history
def test_content_addressed_reader_survives_manifest_rollover(tmp_path):
    from collector import collect_weather
    now = RUN + timedelta(hours=1)
    collect_weather(tmp_path, Weather().client, now)
    meta_path = tmp_path / 'weather/forecast_meta.json'
    old = json.loads(meta_path.read_text())
    def handler(request):
        path = tmp_path / request.url.path.split('/data/', 1)[1]
        if path == meta_path:
            response = path.read_bytes()
            # Publisher advances immediately after the manifest response.
            import hashlib
            body = FORECAST_BODY + b' '
            digest = hashlib.sha256(body).hexdigest()
            (tmp_path / f'weather/payloads/{digest}.json').write_bytes(body)
            (tmp_path / 'weather/forecast.json').write_bytes(body)
            meta_path.write_text(json.dumps({**old, 'sha256': digest}))
            return httpx.Response(200, content=response)
        return httpx.Response(200, content=path.read_bytes()) if path.exists() else httpx.Response(404)
    reader = HistoryReader(lambda: httpx.Client(transport=httpx.MockTransport(handler)), 'https://example.test/data/')
    forecast, _ = reader.weather(now)
    assert forecast['sha256'] == old['sha256']


@pytest.mark.parametrize("quality", ["ACT", "NRE"])
def test_steady_state_load_stays_within_production_envelope(tmp_path, quality):
    """24 h of 15-minute runs: new periods (480) plus at most 4 revalidations per run."""
    base = ACT if quality == "ACT" else ACT.replace(b"QUALITY='ACT'", b"QUALITY='NRE'")

    class Counting(Gse):
        def handler(self, request):
            name = request.url.path.rsplit("/", 1)[-1]
            self.requests.append(name)
            dd, mm, yyyy, hh, mi = NAME.search(name).groups()
            body = relabel(f"{dd}.{mm}.{yyyy} {hh}:{mi}:00", base)
            return httpx.Response(200, content=body, headers={"content-type": "text/xml"})

    gse = Counting()
    collector(tmp_path, gse, hours=12).run(NOW)
    gse.requests.clear()
    for i in range(1, 97):
        collector(tmp_path, gse, hours=12, max_requests=1000).run(NOW + timedelta(minutes=15 * i))
    assert 480 <= len(gse.requests) <= 480 + 4 * 96



# ------------------------------------------------------------ continuity: catch-up and deep backfill

def stored_labels(tmp_path):
    out = set()
    for path in (tmp_path / "gse").rglob("*.csv"):
        out |= {r.period_label_utc for r in parse_day_csv(path.read_text())}
    return out


def test_skipped_runs_widen_the_window_beyond_12_hours(tmp_path):
    gse = Gse()
    collector(tmp_path, gse, hours=12).run(NOW)
    later = NOW + timedelta(hours=20)  # GitHub skipped every run for 20 h
    report, _ = collector(tmp_path, gse, hours=12, max_requests=1000).run(later)
    assert report.lookback_used_hours == pytest.approx(21, abs=0.2)
    assert set(due_labels(later, 20)) <= stored_labels(tmp_path)  # nothing lost
    assert report.backfilled >= 380
    status = json.loads((tmp_path / "status/gse_collector.json").read_text())
    assert status["last_run"]["backfilled"] == report.backfilled


def test_catch_up_is_bounded_at_48_hours(tmp_path):
    gse = Gse()
    collector(tmp_path, gse, hours=1).run(NOW)
    report, _ = collector(tmp_path, gse, hours=12, max_requests=2000).run(NOW + timedelta(days=4))
    assert report.lookback_used_hours == 48


def test_deep_backfill_is_bounded_per_run_and_walks_backwards(tmp_path):
    gse = Gse()
    collector(tmp_path, gse, hours=1).run(NOW)
    before = stored_labels(tmp_path)
    gse.requests.clear()
    report, _ = Collector(tmp_path, gse.client, lookback_hours=1, deep_per_run=20).run(NOW + timedelta(seconds=5))
    assert report.deep_requested == 20 and report.deep_inserted == 20
    added = stored_labels(tmp_path) - before
    assert len(added) == 20 and max(added) < min(before)  # strictly older than what was stored
    deep = json.loads((tmp_path / "status/gse_collector.json").read_text())["deep_backfill"]
    assert datetime.fromisoformat(deep["cursor"]) == min(added) and not deep["done"]


def test_deep_backfill_stops_after_a_day_of_404s(tmp_path):
    cutoff = NOW - timedelta(hours=2)

    class Retention(Gse):
        def handler(self, request):
            name = request.url.path.rsplit("/", 1)[-1]
            dd, mm, yyyy, hh, mi = NAME.search(name).groups()
            label = datetime(int(yyyy), int(mm), int(dd), int(hh), int(mi)).replace(tzinfo=TBILISI).astimezone(UTC)
            if label < cutoff:  # GSE retention ends here
                return httpx.Response(404, headers={"content-type": "text/html"})
            return super().handler(request)

    gse = Retention()
    collector(tmp_path, gse, hours=1).run(NOW)
    done = False
    for i in range(60):
        Collector(tmp_path, gse.client, lookback_hours=1, deep_per_run=20).run(NOW + timedelta(seconds=i + 1))
        deep = json.loads((tmp_path / "status/gse_collector.json").read_text())["deep_backfill"]
        if deep["done"]:
            done = True
            break
    assert done and deep["consecutive_404"] >= 480
    assert min(stored_labels(tmp_path)) >= cutoff  # nothing invented beyond retention
    gse.requests.clear()
    Collector(tmp_path, gse.client, lookback_hours=1, deep_per_run=20).run(NOW + timedelta(minutes=5))
    assert len(gse.requests) <= 3  # finished: no more deep requests


def test_deep_backfill_pauses_while_the_source_fails(tmp_path):
    collector(tmp_path, Gse(), hours=1).run(NOW)
    bad = Gse(override=lambda name: httpx.Response(503, headers={"content-type": "text/html"}))
    report, _ = Collector(tmp_path, bad.client, lookback_hours=1, deep_per_run=20).run(NOW + timedelta(minutes=5))
    assert report.deep_requested == 0


# ------------------------------------------------------------------------------- system balance

def test_balance_parser_on_recorded_file_closes_the_balance():
    from balance import parse_balance
    label, b = parse_balance(ACT)
    assert label == datetime(2026, 11, 14, 20, 9, tzinfo=UTC)
    assert (b.hydro, b.thermal, b.wind, b.solar) == (1075.829346, 313.713287, 73.599297, 0.0)
    assert b.hydro + b.thermal + b.wind + b.solar == pytest.approx(b.generation, abs=0.01)
    assert b.net_interchange == pytest.approx(1536.5354 - 1463.141968, abs=0.01)  # = sum of all tie lines
    assert "wind:ACT" in b.quality and "hydro:SUB" in b.quality


def test_balance_parser_is_strict():
    from app.ingestion.gse_parser import GseParseError
    from balance import parse_balance
    with pytest.raises(GseParseError):
        parse_balance(ACT.replace(b"TOTAL CONSUMPTION", b"TOTAL SOMETHING"))
    with pytest.raises(GseParseError):
        parse_balance(ACT.replace(b"VALUE='1536.535400'", b"VALUE='nan'"))
    with pytest.raises(GseParseError):
        parse_balance(b"<!DOCTYPE x [<!ENTITY a 'b'>]><GSE>&a;</GSE>")


def test_collector_stores_balance_without_extra_requests(tmp_path):
    from store import parse_balance_csv
    gse = Gse()
    report, _ = collector(tmp_path, gse).run(NOW)
    assert report.balance_stored == report.inserted == 20 and report.balance_errors == 0
    assert len(gse.requests) == 20  # same files as the wind aggregate
    rows = parse_balance_csv((tmp_path / "balance/2026/11/2026-11-14.csv").read_text())
    assert len(rows) == 20 and rows[0].consumption_mw == pytest.approx(1536.5354)


def test_balance_refusal_never_blocks_wind(tmp_path):
    broken = ACT.replace(b"TOTAL CONSUMPTION", b"TOTAL SOMETHING")
    gse = Gse()
    gse.base = broken

    def handler(request):
        name = request.url.path.rsplit("/", 1)[-1]
        gse.requests.append(name)
        dd, mm, yyyy, hh, mi = NAME.search(name).groups()
        return httpx.Response(200, content=relabel(f"{dd}.{mm}.{yyyy} {hh}:{mi}:00", broken), headers={"content-type": "text/xml"})

    c = Collector(tmp_path, lambda: httpx.Client(transport=httpx.MockTransport(handler)), lookback_hours=1, deep_per_run=0)
    report, code = c.run(NOW)
    assert report.inserted == 20 and report.balance_errors == 20 and report.balance_stored == 0 and code == 0


def test_stored_wind_without_balance_is_requested_again(tmp_path):
    import shutil
    collector(tmp_path, Gse()).run(NOW)
    shutil.rmtree(tmp_path / "balance")
    gse = Gse()
    report, _ = collector(tmp_path, gse).run(NOW + timedelta(seconds=10))
    assert report.balance_stored == 20 and report.inserted == 0  # wind unchanged, balance filled


def test_gross_import_export_like_gse_website():
    from balance import parse_balance
    _, b = parse_balance(ACT)
    assert b.imports == pytest.approx(40.792889 + 18.299999 + 14.300695)  # AZ + Russia-block lines
    assert b.exports == 0.0
    assert b.imports - b.exports == pytest.approx(b.consumption - b.generation, abs=0.01)  # closure
    # Azerbaijan flowing out (as on 16.11.2026 22:39): export, while Java + Nakaduli stay import
    _, b2 = parse_balance(ACT.replace(b"VALUE='40.792889'", b"VALUE='-24.123554'"))
    assert b2.exports == pytest.approx(24.123554)
    assert b2.imports == pytest.approx(18.299999 + 14.300695)  # Russia sum 0 is ignored, lines used


def test_v1_balance_rows_are_read_and_refetched(tmp_path):
    from store import BALANCE_COLUMNS_V1, parse_balance_csv
    collector(tmp_path, Gse()).run(NOW)
    path = tmp_path / "balance/2026/11/2026-11-14.csv"
    rows = parse_balance_csv(path.read_text())
    v1 = [",".join(BALANCE_COLUMNS_V1)] + [
        ",".join([r.period_label_utc.isoformat(), r.period_label_local, *(repr(x) for x in (r.hydro_mw, r.thermal_mw, r.wind_mw, r.solar_mw, r.generation_mw, r.consumption_mw)),
                  r.quality, r.retrieved_at_utc.isoformat(), r.payload_sha256, "gse-balance-03m/1"]) for r in rows]
    path.write_text("\n".join(v1) + "\n")
    old = parse_balance_csv(path.read_text())
    assert len(old) == 20 and all(r.import_mw is None for r in old)
    report, _ = collector(tmp_path, Gse()).run(NOW + timedelta(seconds=10))
    assert report.balance_stored == 20  # same payloads, now with gross flows
    assert all(r.import_mw is not None for r in parse_balance_csv(path.read_text()))
