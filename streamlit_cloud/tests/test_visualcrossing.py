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


def body(wind_kmh=36.0, temp=8.0):
    t0 = int(NOW.timestamp())
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


def test_out_of_range_and_http_errors_store_nothing(tmp_path):
    with pytest.raises(vc.VCError, match="outside"):
        vc.collect(tmp_path, KEY, lambda u: (200, body(temp=90.0)), NOW)
    assert vc.collect(tmp_path, KEY, lambda u: (429, b""), NOW)["result"] == "failed"
    assert not (tmp_path / vc.ROOT / "manifest.json").exists()


def test_budget_is_within_free_tier():
    records_per_day = len(POINTS) * 48
    assert records_per_day * 31 < 30_000
