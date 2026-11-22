"""Visual Crossing pilot: key never stored, daily budget, unit conversion, strict ranges.
The response is SYNTHETIC, in the documented Timeline API structure (days[].hours[])."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from forecasting import visualcrossing as vc
from forecasting import weather_sources as ws
from forecasting.features import POINTS

NOW = datetime(2026, 11, 21, 8, tzinfo=UTC)
KEY = "secret-test-key-123"


def body(wind_kmh=36.0, temp=8.0, start=NOW):
    t0 = int(start.timestamp())
    hours = [{"datetimeEpoch": t0 + 3600 * h, "temp": temp, "humidity": 80.0, "precip": 0.4, "pressure": 1015.0,
              "cloudcover": 90.0, "windspeed": wind_kmh, "winddir": 270.0, "windgust": 54.0} for h in range(48)]
    return json.dumps({"days": [{"hours": hours[:24]}, {"hours": hours[24:]}]}).encode()


def test_collect_stores_one_daily_run_without_the_key(tmp_path):
    calls = []
    res = vc.collect(tmp_path, KEY, lambda u: calls.append(u) or (200, body()), NOW, clock=lambda: NOW)
    assert res["result"] == "stored" and len(calls) == len(POINTS) and all(KEY in u for u in calls)
    stored = "".join(p.read_bytes().decode("latin-1") for p in tmp_path.rglob("*") if p.is_file())
    assert KEY not in stored  # neither manifest nor gzip table contains the key
    assert vc.collect(tmp_path, KEY, lambda u: (200, body()), NOW + timedelta(hours=5))["result"] == "not_due"
    df = ws.load_run(tmp_path, "visualcrossing", NOW)
    k = df[(df.point == "kutaisi") & (df.variable == "wind_speed_10m")]["value"]
    assert len(k) == 48 and k.iloc[0] == pytest.approx(10.0)  # 36 km/h -> 10 m/s
    assert ws.available_runs(tmp_path, "visualcrossing")[0].retrieved_utc == NOW


def test_without_key_nothing_is_requested(tmp_path):
    assert vc.collect(tmp_path, None, lambda u: pytest.fail("no request without key"), NOW)["result"] == "no_key"


def test_errors_store_no_run_but_record_the_attempt(tmp_path):
    with pytest.raises(vc.VCError, match="outside"):
        vc.collect(tmp_path, KEY, lambda u: (200, body(temp=90.0)), NOW)
    m = json.loads((tmp_path / vc.ROOT / "manifest.json").read_text())
    assert m["runs"] == [] and m["attempts"][-1]["result"] == "error: VCError"
    assert m["attempts"][-1]["requests_used"] == 1 and KEY not in json.dumps(m)


def _counting(fail_at=None, status=429, start=NOW):
    calls = []

    def get(u):
        calls.append(u)
        return (status, b"") if fail_at is not None and len(calls) == fail_at else (200, body(start=start))
    return get, calls


def test_QA_failure_at_point_6_is_not_retried_an_hour_later(tmp_path):
    get, calls = _counting(fail_at=6)
    assert vc.collect(tmp_path, KEY, get, NOW)["result"] == "failed" and len(calls) == 6
    m = json.loads((tmp_path / vc.ROOT / "manifest.json").read_text())
    assert m["attempts"][-1] == {"started": NOW.isoformat(), "reserved": 7, "requests_used": 6,
                                 "result": "http 429 at " + POINTS[5].id}
    for h in range(1, 23):  # every hourly scheduled run for the rest of the day
        res = vc.collect(tmp_path, KEY, get, NOW + timedelta(hours=h))
        assert res["result"] == "not_due"
    assert len(calls) == 6  # no further request that day


def test_QA_429_at_first_point_waits_a_day_then_retries_once(tmp_path):
    get, calls = _counting(fail_at=1)
    assert vc.collect(tmp_path, KEY, get, NOW)["result"] == "failed" and len(calls) == 1
    assert vc.collect(tmp_path, KEY, get, NOW + timedelta(hours=1))["result"] == "not_due"
    ok, ok_calls = _counting(start=NOW + timedelta(hours=24))
    assert vc.collect(tmp_path, KEY, ok, NOW + timedelta(hours=24), clock=lambda: NOW)["result"] == "stored"
    assert len(ok_calls) == 7


def test_QA_never_more_than_the_daily_budget_in_any_24h(tmp_path):
    """Hourly invocations for three days, mixing failures and successes: rolling 24 h use <= 7."""
    log = []
    for h in range(72):
        t = NOW + timedelta(hours=h)
        get, calls = _counting(fail_at=3 if h % 2 == 0 else None)
        vc.collect(tmp_path, KEY, get, t, clock=lambda t=t: t)
        log += [t] * len(calls)
    for t in log:
        assert sum(1 for x in log if t <= x < t + timedelta(hours=24)) <= vc.DAILY_REQUESTS


def test_QA_budget_guard_blocks_even_if_the_interval_were_bypassed(tmp_path):
    m = {"source": "visualcrossing", "runs": [], "attempts": [
        {"started": (NOW - timedelta(hours=23, minutes=30)).isoformat(), "reserved": 7, "requests_used": 7,
         "result": "stored"}]}
    (tmp_path / vc.ROOT).mkdir(parents=True)
    (tmp_path / vc.ROOT / "manifest.json").write_text(json.dumps(m))
    res = vc.collect(tmp_path, KEY, lambda u: pytest.fail("over budget"), NOW)
    assert res["result"] == "budget_exhausted" and res["requests_used_24h"] == 7


def test_budget_is_within_free_tier():
    records_per_day = len(POINTS) * 48
    assert records_per_day * 31 < 30_000


# --- QA residual: the reservation must be durable remotely BEFORE any request (two-phase) ---

def test_two_phase_reserve_then_collect_for_the_same_run(tmp_path):
    assert vc.reserve(tmp_path, KEY, NOW, "101")["result"] == "reserved"
    m = json.loads((tmp_path / vc.ROOT / "manifest.json").read_text())
    assert m["attempts"][-1]["requests_used"] == 7  # counted in full before any request
    get, calls = _counting()
    assert vc.collect(tmp_path, KEY, get, NOW, clock=lambda: NOW, run_id="101")["result"] == "stored"
    assert len(calls) == 7


def test_no_request_without_this_runs_pushed_reservation(tmp_path):
    get, calls = _counting()
    assert vc.collect(tmp_path, KEY, get, NOW, run_id="101")["result"] == "not_reserved"
    vc.reserve(tmp_path, KEY, NOW, "101")
    assert vc.collect(tmp_path, KEY, get, NOW, run_id="202")["result"] == "not_reserved"  # another run
    assert vc.collect(tmp_path, KEY, get, NOW, run_id="unpushed")["result"] == "not_reserved"
    assert calls == []


def test_crash_after_reservation_still_blocks_further_requests_for_a_day(tmp_path):
    """Runner dies after the reservation was pushed (no collect): the pushed state alone keeps
    the next 22 hourly runs from reserving or requesting again."""
    vc.reserve(tmp_path, KEY, NOW, "101")
    for h in range(1, 23):
        assert vc.reserve(tmp_path, KEY, NOW + timedelta(hours=h), str(200 + h))["result"] == "not_due"
    assert vc.reserve(tmp_path, KEY, NOW + timedelta(hours=24), "300")["result"] == "reserved"


def test_sources_skips_visual_crossing_when_the_reservation_was_not_pushed(tmp_path, monkeypatch):
    from forecasting import run as frun
    monkeypatch.setenv("GITHUB_RUN_ID", "101")
    monkeypatch.delenv("VC_RESERVATION_PUSHED", raising=False)
    monkeypatch.setenv("VISUAL_CROSSING_API_KEY", KEY)
    vc.reserve(tmp_path, KEY, NOW, "101")
    monkeypatch.setattr(ws, "collect", lambda *a, **k: {"source": a[1], "result": "unchanged"})
    seen = []
    orig = vc.collect
    monkeypatch.setattr(vc, "collect", lambda *a, **k: seen.append(k.get("run_id")) or orig(*a, **k))
    res = frun.cmd_sources(tmp_path, NOW)
    assert seen == ["unpushed"]
    assert next(r for r in res["sources"] if r["source"] == "visualcrossing")["result"] == "not_reserved"


def test_workflow_pushes_the_reservation_before_collecting():
    from pathlib import Path
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/weather-sources.yml").read_text(encoding="utf-8")
    assert wf.index("run vc-reserve") < wf.index("run sources")
    block = wf[wf.index("Reserve the Visual Crossing quota"):wf.index("Collect new runs")]
    assert block.index("push -q origin forecast-data") < block.index('VC_RESERVATION_PUSHED=true')


def test_incomplete_response_stores_nothing_and_still_counts_the_attempt(tmp_path):
    t0 = int(NOW.timestamp())
    short = json.dumps({"days": [{"hours": [{"datetimeEpoch": t0 + 3600 * h, "temp": 8.0, "windspeed": 20.0}
                                              for h in range(10)]}]}).encode()
    calls = []
    res = vc.collect(tmp_path, KEY, lambda u: calls.append(u) or (200, short), NOW)
    assert res["result"] == "failed" and "incomplete" in res["error"] and len(calls) == 1
    m = json.loads((tmp_path / vc.ROOT / "manifest.json").read_text())
    assert m["runs"] == [] and m["attempts"][-1]["requests_used"] == 1
    assert not (tmp_path / vc.ROOT / "runs").exists()
    no_wind = json.dumps({"days": [{"hours": [{"datetimeEpoch": t0 + 3600 * h, "temp": 8.0} for h in range(48)]}]})
    assert vc.collect(tmp_path / "b", KEY, lambda u: (200, no_wind.encode()), NOW)["result"] == "failed"
