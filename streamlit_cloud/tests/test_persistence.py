"""Durable store, scheduled collector and history reader (offline, recorded GSE payloads)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from collector import Collector, due_labels
from history import HistoryReader, collector_age
from store import Record, StoreFormatError, day_path, merge, parse_day_csv, render_day_csv

ROOT = Path(__file__).resolve().parents[2]
ACT = (ROOT / "backend/tests/fixtures/gse/real_act_15112026_0009.xml").read_bytes()
NAME = re.compile(r"_(\d\d)(\d\d)(\d{4})_(\d\d)(\d\d)\.XML$")
NOW = datetime(2026, 11, 14, 20, 20, tzinfo=UTC)  # newest due label 20:18 UTC (00:18 Tbilisi)


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
