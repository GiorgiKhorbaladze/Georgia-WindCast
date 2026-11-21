"""Independent NWP sources (GFS, ECMWF IFS) - Issue #57. Index parsing uses REAL index lines from
the AWS Open Data files (20.11.2026 12 UTC run); GRIB decoding uses synthetic messages built with
ecCodes' own GRIB2 sample (no network)."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from forecasting import weather_sources as ws
from forecasting.features import POINTS, Run, asof

FIX = Path(__file__).resolve().parent / "fixtures" / "weather_sources"
RUN = datetime(2026, 11, 20, 12, tzinfo=UTC)


def test_gfs_idx_selects_fields_and_byte_ranges_from_real_index():
    msgs = ws.parse_gfs_idx((FIX / "gfs_f003_fields.idx").read_text(), "u", 3)
    keys = {m.key for m in msgs}
    assert {"t2", "rh2", "sp", "u10", "v10", "u100", "v100", "tp", "tcc"} <= keys
    t2 = next(m for m in msgs if m.key == "t2")
    lines = (FIX / "gfs_f003_fields.idx").read_text().splitlines()
    i = next(k for k, ln in enumerate(lines) if ":TMP:2 m above ground:" in ln)
    nxt = int(lines[i + 1].split(":")[1])  # the record right after TMP in the real file
    assert (t2.offset, t2.length) == (411653623, nxt - 411653623)
    assert all(m.period == (0, 3) for m in msgs if m.key == "tp")
    assert not any(m.key == "tcc" and m.period for m in msgs)  # instantaneous cloud cover only


def test_ecmwf_index_selects_surface_fields_from_real_index():
    msgs = ws.parse_ecmwf_index((FIX / "ecmwf_3h.index").read_text(), "u", 3)
    assert {m.key for m in msgs} == {"msl", "sp", "t2", "td2", "u10", "v10", "u100", "v100", "gust", "tp", "tcc"}
    assert all(m.length > 0 for m in msgs)
    assert next(m for m in msgs if m.key == "tp").period == (0, 3)  # accumulated from the run start


def test_unit_conversions():
    assert ws.rh_from_dewpoint(20.0, 20.0) == pytest.approx(100.0)
    assert 40 < ws.rh_from_dewpoint(20.0, 6.0) < 45
    speed, direction = ws.wind(0.0, -5.0)  # air moving south = wind FROM the north
    assert speed == pytest.approx(5.0) and direction == pytest.approx(0.0)
    assert ws.wind(-5.0, 0.0)[1] == pytest.approx(90.0)  # moving west = from the east


def test_precipitation_is_de_accumulated_without_inventing_values():
    # GFS style: windows resetting every 6 h; IFS style: cumulative from the start
    gfs = {(0, 3): 1.0, (0, 6): 2.5, (6, 9): 0.4}
    assert ws.interval_precip(gfs, [0, 3, 6, 9]) == {3: 1.0, 6: 1.5, 9: 0.4}
    ifs = {(0, 3): 0.001, (0, 6): 0.003}
    out = ws.interval_precip(ifs, [0, 3, 6, 9], tol=0.00005)
    assert out[3] == pytest.approx(0.001) and out[6] == pytest.approx(0.002) and 9 not in out  # no value at 9 h


def test_normalise_refuses_out_of_range_values():
    raw = {("t2", 0, i): 400.0 for i in range(len(POINTS))}  # 126.85 degC
    with pytest.raises(ws.SourceError, match="outside"):
        ws.normalise("gfs", raw, {}, RUN, [0])


def test_http_retries_slowdown_then_fails_cleanly():
    calls = []

    def get(url, headers):
        calls.append(headers)
        return (503, b"", {}) if len(calls) < 3 else (206, b"ok", {})
    http = ws.Http(get, sleep=lambda s: None)
    assert http.fetch("u", (0, 1))[0] == b"ok" and calls[0] == {"Range": "bytes=0-1"}
    with pytest.raises(ws.SourceError, match="404"):
        ws.Http(lambda u, h: (404, b"", {}), sleep=lambda s: None).fetch("u")


eccodes = pytest.importorskip("eccodes")


def grib(value_fn):
    """A real GRIB2 message (ecCodes sample, regular lat/lon over Georgia) with given values."""
    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    eccodes.codes_set_key_vals(gid, {"Ni": 21, "Nj": 13, "latitudeOfFirstGridPointInDegrees": 44.0,
                                     "longitudeOfFirstGridPointInDegrees": 40.0, "latitudeOfLastGridPointInDegrees": 41.0,
                                     "longitudeOfLastGridPointInDegrees": 45.0, "iDirectionIncrementInDegrees": 0.25,
                                     "jDirectionIncrementInDegrees": 0.25})
    lats = [44.0 - 0.25 * j for j in range(13)]
    lons = [40.0 + 0.25 * i for i in range(21)]
    eccodes.codes_set_values(gid, [value_fn(la, lo) for la in lats for lo in lons])
    body = eccodes.codes_get_message(gid)
    eccodes.codes_release(gid)
    return body


def test_decode_reads_the_nearest_grid_point():
    body = grib(lambda la, lo: la * 100 + lo)
    vals = ws.decode_points(body)
    for p, (v, la, lo) in zip(POINTS, vals):
        assert abs(la - p.lat) <= 0.125 + 1e-9 and abs(lo - p.lon) <= 0.125 + 1e-9
        assert v == pytest.approx(la * 100 + lo, abs=1e-3)


class FakeS3:
    """Serves an ECMWF-style index + GRIB for each step; values per field are constants."""

    VALUES = {"msl": 101300.0, "sp": 92000.0, "2t": 283.15, "2d": 278.15, "10u": 3.0, "10v": 4.0,
              "100u": 6.0, "100v": 8.0, "10fg": 9.0, "tcc": 0.5}

    def __init__(self, steps):
        self.steps, self.files = steps, {}
        for step in steps:
            parts, index, off = [], [], 0
            for param, val in {**self.VALUES, "tp": 0.001 * step}.items():
                b = grib(lambda la, lo, v=val: v)
                index.append(json.dumps({"param": param, "levtype": "sfc", "_offset": off, "_length": len(b)}))
                parts.append(b)
                off += len(b)
            self.files[ws.ecmwf_file(RUN, step, "grib2")] = b"".join(parts)
            self.files[ws.ecmwf_file(RUN, step, "index")] = "\n".join(index).encode()
        self.requests = 0

    def get(self, url, headers):
        self.requests += 1
        if url not in self.files:
            return 404, b"", {}
        body = self.files[url]
        if "Range" in headers:
            a, b = (int(x) for x in headers["Range"].split("=")[1].split("-"))
            return 206, body[a:b + 1], {"last-modified": "Fri, 20 Nov 2026 19:34:01 GMT"}
        return 200, body, {}


def test_collect_stores_canonical_table_once_with_provenance(tmp_path):
    steps = (0, 3, 6)
    s3 = FakeS3(steps)
    now = RUN + timedelta(hours=8)
    res = ws.collect(tmp_path, "ecmwf", ws.Http(s3.get, sleep=lambda s: None), now, steps, clock=lambda: now)
    assert res["result"] == "stored"
    n = s3.requests
    assert ws.collect(tmp_path, "ecmwf", ws.Http(s3.get, sleep=lambda s: None), now, steps)["result"] == "unchanged"
    assert s3.requests - n <= 2  # only the availability probe, no data download
    df = ws.load_run(tmp_path, "ecmwf", RUN)
    k = df[(df.point == "kartli_ruisi") & (df.valid_utc == RUN + timedelta(hours=3))].set_index("variable")["value"]
    assert k["temperature_2m"] == pytest.approx(10.0) and k["pressure_msl"] == pytest.approx(1013.0)
    assert k["wind_speed_10m"] == pytest.approx(5.0) and k["wind_speed_100m"] == pytest.approx(10.0)
    assert k["cloud_cover"] == pytest.approx(50.0) and k["precipitation"] == pytest.approx(3.0)  # 3 mm in 0-3 h
    assert 70 < k["relative_humidity_2m"] < 72
    first = df[(df.valid_utc == RUN)]
    assert "wind_gusts_10m" not in set(first["variable"]) and "precipitation" not in set(first["variable"])
    entry = json.loads((tmp_path / ws.ROOT / "ecmwf" / "manifest.json").read_text())["runs"][0]
    assert entry["retrieved"] == now.isoformat() and entry["published"] == "2026-11-20T19:34:01+00:00"
    runs = ws.available_runs(tmp_path, "ecmwf")
    assert asof(runs, now - timedelta(minutes=1)) is None and asof(runs, now) == Run(RUN, now)


def test_missing_last_step_means_run_not_complete(tmp_path):
    s3 = FakeS3((0, 3))  # step 6 not yet published
    res = ws.collect(tmp_path, "ecmwf", ws.Http(s3.get, sleep=lambda s: None), RUN + timedelta(hours=8), (0, 3, 6))
    assert res["result"] == "no_complete_run"


def test_sources_workflow_is_isolated_keyless_and_unpublished():
    root = Path(__file__).resolve().parents[2]
    wf = (root / ".github/workflows/weather-sources.yml").read_text(encoding="utf-8")
    assert "group: forecast-data" in wf and "pull_request" not in wf and "secrets." in wf
    assert "push -q origin forecast-data" in wf and "origin data" not in wf
    assert "API_KEY" not in wf.upper().replace("API KEY", "")  # no key needed for AWS Open Data
    import mwmodel
    assert mwmodel.PUBLISH_FORECAST is False


def test_tournament_builds_a_variant_per_source_and_predictor_set(tmp_path, monkeypatch):
    from forecasting import run as frun
    from forecasting import tournament

    calls = []
    monkeypatch.setattr(tournament, "run", lambda obs, weather=None: calls.append(weather) or
                        {"status": {}, "scores": [], "predictions": __import__("pandas").DataFrame()})
    monkeypatch.setattr(frun, "load_obs", lambda *a, **k: __import__("pandas").Series(dtype=float))
    s3 = FakeS3((0, 3, 6))
    ws.collect(tmp_path, "ecmwf", ws.Http(s3.get, sleep=lambda s: None), RUN + timedelta(hours=8), (0, 3, 6))
    res = frun.cmd_tournament(tmp_path, tmp_path, RUN + timedelta(days=1))
    assert res["variants"] == ["gse_only", "ecmwf_local_weather", "ecmwf_local_plus_west"]
    assert res["sources"]["ecmwf"]["runs"] == 1 and res["sources"]["gfs"]["runs"] == 0
    report = json.loads((tmp_path / "evaluation" / "tournament.json").read_text())
    assert "weather_ablation" not in report


def test_variant_labels_name_the_source():
    import forecast_page
    assert forecast_page._variant_label("gfs_local_plus_west", "en").startswith("NOAA GFS: ")
    assert forecast_page._variant_label("gse_only", "ka") == "მხოლოდ ფაქტობრივი გენერაცია"



# --- QA W1/W2/provenance (#65 audit, 21.11.2026) -------------------------------------------
def test_W1_missing_or_inconsistent_precipitation_is_never_dry():
    assert ws.interval_precip({(0, 3): math.nan}, [0, 3]) == {}  # NaN is missing, not 0 mm
    assert ws.interval_precip({}, [0, 3]) == {}  # no accumulation at all: no value
    assert ws.interval_precip({(0, 6): 2.0}, [0, 3, 6]) == {}  # base (0,3) missing: no value
    flags = []
    assert ws.interval_precip({(0, 3): 10.0, (0, 6): 2.0}, [0, 3, 6], tol=0.05, flags=flags) == {3: 10.0}
    assert flags and "negative" in flags[0]  # -8 mm is flagged, not hidden as 0
    assert ws.interval_precip({(0, 3): 1.0, (0, 6): 0.98}, [0, 3, 6], tol=0.05) == {3: 1.0, 6: 0.0}  # packing noise
    assert ws.interval_precip({(0, 3): 0.001, (0, 6): 0.003}, [0, 3, 6], tol=0.00005)[6] == pytest.approx(0.002)


def test_W2_run_becomes_available_only_after_retrieval_completes(tmp_path):
    steps = (0, 3, 6)
    start = RUN + timedelta(hours=8)
    done = start + timedelta(minutes=5)
    ws.collect(tmp_path, "ecmwf", ws.Http(FakeS3(steps).get, sleep=lambda s: None), start, steps, clock=lambda: done)
    entry = json.loads((tmp_path / ws.ROOT / "ecmwf" / "manifest.json").read_text())["runs"][0]
    assert entry["started"] == start.isoformat() and entry["retrieved"] == done.isoformat()
    runs = ws.available_runs(tmp_path, "ecmwf")
    assert asof(runs, start + timedelta(minutes=2)) is None  # issue during the download: excluded
    assert asof(runs, done) is not None


def test_W2_each_source_gets_its_own_completion_time(tmp_path):
    from forecasting import run as frun
    times = iter([RUN + timedelta(hours=8, minutes=m) for m in (3, 9)])
    import types
    stub = types.SimpleNamespace()

    def fake_collect(out, source, http, now, steps=ws.STEPS, clock=None):
        return {"source": source, "retrieved": clock().isoformat()}
    orig = ws.collect
    ws.collect = fake_collect
    try:
        frun_dt = frun.datetime
        class Clock(frun_dt):
            @classmethod
            def now(cls, tz=None):
                return next(times)
        frun.datetime = Clock
        res = frun.cmd_sources(tmp_path, RUN)
    finally:
        ws.collect, frun.datetime = orig, frun_dt
    r = {x["source"]: x.get("retrieved") for x in res["sources"] if x["source"] in ("gfs", "ecmwf")}
    assert r["gfs"] != r["ecmwf"]


def test_provenance_keeps_every_message_and_parses_publication_dates(tmp_path):
    steps = (0, 3)
    now = RUN + timedelta(hours=8)
    ws.collect(tmp_path, "ecmwf", ws.Http(FakeS3(steps).get, sleep=lambda s: None), now, steps, clock=lambda: now)
    root = tmp_path / ws.ROOT / "ecmwf"
    entry = json.loads((root / "manifest.json").read_text())["runs"][0]
    import gzip, hashlib
    raw = gzip.decompress((root / entry["evidence"]).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == entry["evidence_sha256"]
    msgs = json.loads(raw)
    assert len(msgs) == entry["messages"] == 2 * 11
    assert all(m["sha256"] and m["offset"] >= 0 and m["length"] > 0 and m["last_modified"] for m in msgs)
    assert {(m["field"], m["step"]) for m in msgs} >= {("t2", 0), ("tp", 3)}
    assert ws._http_date("Sat, 21 Nov 2026 00:27:03 GMT") > ws._http_date("Fri, 20 Nov 2026 23:59:59 GMT")


def _sources_with(monkeypatch, tmp_path, outcome):
    from forecasting import run as frun

    def fake_collect(out, source, http, now, steps=ws.STEPS, clock=None):
        if outcome[source] == "fail":
            raise TimeoutError("read timeout")
        return {"source": source, "result": outcome[source]}
    monkeypatch.setattr(ws, "collect", fake_collect)
    return frun


def _manifest(tmp_path, source, run):
    p = tmp_path / ws.ROOT / source
    p.mkdir(parents=True, exist_ok=True)
    (p / "manifest.json").write_text(json.dumps({"source": source, "runs": [{"run": run.isoformat()}]}))


def test_one_failing_source_is_recorded_but_does_not_fail_the_job(tmp_path, monkeypatch):
    now = RUN + timedelta(hours=8)
    for s in ("gfs", "ecmwf"):
        _manifest(tmp_path, s, RUN)
    frun = _sources_with(monkeypatch, tmp_path, {"gfs": "fail", "ecmwf": "unchanged"})
    monkeypatch.setattr(frun, "datetime", type("D", (datetime,), {"now": classmethod(lambda c, tz=None: now)}))
    assert frun.main(["sources", "--data-dir", str(tmp_path), "--out-dir", str(tmp_path)]) == 0
    h = json.loads((tmp_path / ws.ROOT / "health.json").read_text())
    assert h["sources"]["gfs"]["consecutive_failures"] == 1 and "timeout" in h["sources"]["gfs"]["last_error"]
    assert h["sources"]["ecmwf"]["consecutive_failures"] == 0 and h["alert"] == []


def test_all_sources_failing_or_stale_is_never_green(tmp_path, monkeypatch):
    now = RUN + timedelta(hours=8)
    _manifest(tmp_path, "gfs", RUN)
    _manifest(tmp_path, "ecmwf", RUN - timedelta(hours=24))  # stale: last stored run 32 h old
    frun = _sources_with(monkeypatch, tmp_path, {"gfs": "fail", "ecmwf": "fail"})
    monkeypatch.setattr(frun, "datetime", type("D", (datetime,), {"now": classmethod(lambda c, tz=None: now)}))
    args = ["sources", "--data-dir", str(tmp_path), "--out-dir", str(tmp_path)]
    assert frun.main(args) == 2
    h = json.loads((tmp_path / ws.ROOT / "health.json").read_text())
    assert h["alert"][0] == "every source failed in this attempt" and any("ecmwf" in a for a in h["alert"])
    assert frun.main(args) == 2
    assert json.loads((tmp_path / ws.ROOT / "health.json").read_text())["sources"]["gfs"]["consecutive_failures"] == 2


def test_sources_workflow_commits_partial_results_then_fails_on_alert():
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/weather-sources.yml").read_text(encoding="utf-8")
    assert 'echo "rc=$rc" >> "$GITHUB_OUTPUT"' in wf
    assert wf.index("Commit and push") < wf.index("steps.collect.outputs.rc == '2'")


def test_scheduled_collection_is_off_until_the_owner_enables_it():
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/weather-sources.yml").read_text(encoding="utf-8")
    assert "if: github.event_name == 'workflow_dispatch' || vars.WEATHER_SOURCES_ENABLED == 'true'" in wf
