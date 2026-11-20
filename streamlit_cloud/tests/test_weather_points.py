"""Multi-point weather collection (Issue #57): one request per new run, strict parse, as-of, backoff.

The response fixture is SYNTHETIC (values generated here) but follows the exact structure of the
stored real Open-Meteo icon_global payloads (list of locations, hourly_units, unixtime axis).
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from forecasting import weather_points as wp
from forecasting.features import POINTS, UNITS, VARIABLES, Run, asof

RUN = datetime(2026, 11, 20, 12, tzinfo=UTC)
NOW = datetime(2026, 11, 20, 16, 50, tzinfo=UTC)


def payload(hours=96, unit_override=None, value=None, cells=None):
    t0 = int(RUN.timestamp())
    locs = []
    for i, p in enumerate(POINTS):
        units = {"time": "unixtime", **UNITS, **(unit_override or {})}
        hourly = {"time": [t0 + 3600 * h for h in range(hours)]}
        for v in VARIABLES:
            base = {"°C": 5.0, "%": 70.0, "mm": 0.2, "hPa": 1012.0, "m/s": 6.0, "°": 270.0}[UNITS[v]]
            hourly[v] = [value if value is not None else base for _ in range(hours)]
        lat, lon = (cells or {}).get(p.id, (round(p.lat * 8) / 8, round(p.lon * 8) / 8))
        locs.append({"latitude": lat, "longitude": lon, "elevation": 100.0 + i, "hourly_units": units, "hourly": hourly})
    return json.dumps(locs).encode()


def meta(run=RUN):
    return json.dumps({"last_run_initialisation_time": int(run.timestamp())}).encode()


class Fake:
    def __init__(self, body=None, data_status=200, runs=(RUN, RUN)):
        self.calls, self.body, self.data_status, self.runs = [], body or payload(), data_status, list(runs)

    def __call__(self, u):
        self.calls.append(u)
        if u.endswith("meta.json"):
            return wp.Response(200, meta(self.runs.pop(0) if self.runs else RUN))
        return wp.Response(self.data_status, self.body if self.data_status == 200 else b'{"error":true}')


def data_dir(tmp_path, run=RUN):
    d = tmp_path / "data" / "weather"
    d.mkdir(parents=True)
    (d / "forecast_meta.json").write_text(json.dumps({"run": run.isoformat()}))
    return tmp_path / "data"


def test_request_is_one_batched_call_with_all_points_and_variables():
    u = wp.url()
    assert u.count("latitude=") == 1 and u.split("latitude=")[1].split("&")[0].count(",") == len(POINTS) - 1
    for v in VARIABLES:
        assert v in u
    assert "models=icon_global" in u and "wind_speed_unit=ms" in u


def test_new_run_is_stored_once_with_hash_and_retrieval_time(tmp_path):
    fake, out = Fake(), tmp_path / "out"
    res = wp.collect(out, data_dir(tmp_path), fake, NOW)
    assert res["result"] == "stored" and len(fake.calls) == 3  # meta, data, meta
    again = wp.collect(out, data_dir(tmp_path) if False else tmp_path / "data", fake, NOW + timedelta(minutes=15))
    assert again["result"] == "unchanged" and len(fake.calls) == 3  # no request at all
    entry = json.loads((out / wp.ROOT / "manifest.json").read_text())["runs"][0]
    assert entry["retrieved"] == NOW.isoformat() and len(entry["sha256"]) == 64
    assert gzip.decompress((out / wp.ROOT / entry["file"]).read_bytes()) == fake.body
    frame = wp.load_run(out, RUN)
    assert set(frame["point"]) == {p.id for p in POINTS} and set(frame["variable"]) == set(VARIABLES)


def test_run_change_during_request_stores_nothing(tmp_path):
    later = RUN + timedelta(hours=6)
    res = wp.collect(tmp_path / "out", data_dir(tmp_path), Fake(runs=(RUN, later)), NOW)
    assert res["result"] == "failed" and not (tmp_path / "out" / wp.ROOT / "manifest.json").exists()


def test_rate_limit_backs_off_for_an_hour(tmp_path):
    fake = Fake(data_status=429)
    assert wp.collect(tmp_path / "out", data_dir(tmp_path), fake, NOW)["reason"] == "data http 429"
    n = len(fake.calls)
    assert wp.collect(tmp_path / "out", tmp_path / "data", fake, NOW + timedelta(minutes=30))["result"] == "backing_off"
    assert len(fake.calls) == n
    fake.data_status = 200
    assert wp.collect(tmp_path / "out", tmp_path / "data", fake, NOW + timedelta(minutes=61))["result"] == "stored"


@pytest.mark.parametrize("body, msg", [
    (payload(unit_override={"temperature_2m": "°F"}), "unit"),
    (payload(value=5000.0), "outside"),
    (b"[]", "locations"),
])
def test_schema_drift_is_refused(tmp_path, body, msg):
    res = wp.collect(tmp_path / "out", data_dir(tmp_path), Fake(body=body), NOW)
    assert res["result"] == "failed" and msg in res["reason"]


def test_shared_grid_cells_are_reported():
    _frame, cells = wp.parse(payload(cells={"kartli_ruisi": (42.0, 44.0), "tbilisi": (42.0, 44.0)}))
    assert ["kartli_ruisi", "tbilisi"] in wp.shared_cells(cells)


def test_stored_runs_respect_as_of_rule(tmp_path):
    wp.collect(tmp_path / "out", data_dir(tmp_path), Fake(), NOW)
    runs = wp.available_runs(tmp_path / "out")
    assert asof(runs, NOW - timedelta(minutes=1)) is None  # run existed, but was not yet retrieved
    assert asof(runs, NOW) == Run(RUN, NOW)


def test_tampered_payload_is_refused(tmp_path):
    out = tmp_path / "out"
    wp.collect(out, data_dir(tmp_path), Fake(), NOW)
    f = next((out / wp.ROOT / "runs").iterdir())
    with gzip.GzipFile(f, "wb", mtime=0) as fh:
        fh.write(payload(value=1.0))
    with pytest.raises(wp.WeatherSchemaError, match="altered"):
        wp.load_run(out, RUN)
