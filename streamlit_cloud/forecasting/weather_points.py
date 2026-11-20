"""Multi-point weather forecasts for the forecasting models (Issue #57, owner-approved 20.11.2026).

One batched Open-Meteo ICON request per NEW model run, at forecasting.features.POINTS, with the
variables in forecasting.features.VARIABLES. The new run is taken from the GSE collector's own
metadata (``data`` branch ``weather/forecast_meta.json``), so this module adds no polling of its
own. The run is confirmed against Open-Meteo's metadata before and after the request; if it
changed in between, nothing is stored. After a refused or failed request (429, HTTP error,
schema drift) no request is made for ``RETRY_AFTER``.

Stored in the ``forecast-data`` branch: ``weather/points/runs/<run>.json.gz`` (the exact response
bytes, gzip) and ``weather/points/manifest.json`` (run, retrieval time, URL, SHA-256 of the raw
response, grid cell of every point). The retrieval time is what makes as-of use possible: a model
issued at T may use a run only if run <= T and retrieved <= T.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from forecasting.features import POINTS, RANGES, UNITS, VARIABLES, Run

BASE = "https://api.open-meteo.com"
MODEL, META_MODEL = "icon_global", "dwd_icon"
FORECAST_DAYS = 4
RETRY_AFTER = timedelta(hours=1)
ROOT = Path("weather") / "points"


class WeatherSchemaError(ValueError):
    pass


@dataclass
class Response:
    status: int
    body: bytes


Fetch = Callable[[str], Response]


def url() -> str:
    params = {"latitude": ",".join(f"{p.lat:.6f}" for p in POINTS),
              "longitude": ",".join(f"{p.lon:.6f}" for p in POINTS),
              "hourly": ",".join(VARIABLES), "models": MODEL, "forecast_days": FORECAST_DAYS,
              "wind_speed_unit": "ms", "timeformat": "unixtime", "timezone": "GMT"}
    return f"{BASE}/v1/forecast?{urlencode(params, safe=',')}"


def meta_url() -> str:
    return f"{BASE}/data/{META_MODEL}/static/meta.json"


def run_time(meta_body: bytes) -> datetime:
    t = json.loads(meta_body)["last_run_initialisation_time"]
    if not isinstance(t, int | float) or isinstance(t, bool):
        raise WeatherSchemaError("meta: last_run_initialisation_time missing")
    return datetime.fromtimestamp(t, UTC)


def parse(body: bytes) -> tuple[pd.DataFrame, list[dict]]:
    """Strict parse -> long table (point, valid_utc, variable, value) and grid cells per point."""
    data = json.loads(body)
    if not isinstance(data, list) or len(data) != len(POINTS):
        raise WeatherSchemaError(f"expected {len(POINTS)} locations")
    rows, cells = [], []
    for point, loc in zip(POINTS, data, strict=True):
        units, hourly = loc.get("hourly_units") or {}, loc.get("hourly") or {}
        times = hourly.get("time")
        if units.get("time") != "unixtime" or not times or any(b - a != 3600 for a, b in zip(times, times[1:])):
            raise WeatherSchemaError(f"{point.id}: time axis is not hourly unixtime")
        cells.append(dict(point=point.id, grid_latitude=loc.get("latitude"), grid_longitude=loc.get("longitude"),
                          elevation_m=loc.get("elevation")))
        valid = pd.to_datetime(times, unit="s", utc=True)
        for var in VARIABLES:
            if units.get(var) != UNITS[var]:
                raise WeatherSchemaError(f"{point.id}.{var}: unit {units.get(var)!r}, expected {UNITS[var]!r}")
            values = hourly.get(var)
            if not isinstance(values, list) or len(values) != len(times):
                raise WeatherSchemaError(f"{point.id}.{var}: length mismatch")
            lo, hi = RANGES[UNITS[var]]
            for t, v in zip(valid, values, strict=True):
                if v is None:
                    continue  # missing stays missing
                if isinstance(v, bool) or not isinstance(v, int | float) or not lo <= v <= hi:
                    raise WeatherSchemaError(f"{point.id}.{var}: value {v!r} outside {lo}..{hi}")
                rows.append((point.id, t, var, float(v)))
    return pd.DataFrame(rows, columns=["point", "valid_utc", "variable", "value"]), cells


def shared_cells(cells: list[dict]) -> list[list[str]]:
    """Groups of points that resolved to the same model grid cell (not independent predictors)."""
    by: dict[tuple, list[str]] = {}
    for c in cells:
        by.setdefault((c["grid_latitude"], c["grid_longitude"]), []).append(c["point"])
    return [v for v in by.values() if len(v) > 1]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def collect(out: Path, data_dir: Path, fetch: Fetch, now: datetime) -> dict:
    """At most one data request, and only for a run newer than the last stored one."""
    root = out / ROOT
    manifest_path, state_path = root / "manifest.json", root / "state.json"
    manifest, state = _load(manifest_path), _load(state_path)
    runs = manifest.get("runs", [])
    collector_meta = _load(data_dir / "weather" / "forecast_meta.json")
    if not collector_meta.get("run"):
        return {"result": "no_collector_run"}
    expected = datetime.fromisoformat(collector_meta["run"])
    if any(r["run"] == expected.isoformat() for r in runs):
        return {"result": "unchanged", "run": expected.isoformat()}
    if state.get("failed_at") and now - datetime.fromisoformat(state["failed_at"]) < RETRY_AFTER:
        return {"result": "backing_off", "since": state["failed_at"]}
    root.mkdir(parents=True, exist_ok=True)

    def fail(reason: str) -> dict:
        state.update(failed_at=now.isoformat(), reason=reason)
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        return {"result": "failed", "reason": reason}

    try:
        before = fetch(meta_url())
        if before.status != 200:
            return fail(f"meta http {before.status}")
        run = run_time(before.body)
        if run != expected:
            return {"result": "run_mismatch", "collector": expected.isoformat(), "provider": run.isoformat()}
        req = url()
        got = fetch(req)
        if got.status != 200:
            return fail(f"data http {got.status}")
        frame, cells = parse(got.body)
        after = fetch(meta_url())
        if after.status != 200 or run_time(after.body) != run:
            return fail("run changed during the request")
    except WeatherSchemaError as exc:
        return fail(f"schema: {exc}")
    except Exception as exc:  # network errors: back off, keep everything stored so far
        return fail(type(exc).__name__)
    sha = hashlib.sha256(got.body).hexdigest()
    name = f"{run:%Y%m%dT%H%MZ}.json.gz"
    (root / "runs").mkdir(exist_ok=True)
    with gzip.GzipFile(root / "runs" / name, "wb", mtime=0) as fh:
        fh.write(got.body)
    runs.append(dict(run=run.isoformat(), retrieved=now.isoformat(), url=req, sha256=sha, file=f"runs/{name}",
                     model=MODEL, points=[p.id for p in POINTS], variables=list(VARIABLES), cells=cells,
                     shared_cells=shared_cells(cells), values=int(len(frame))))
    manifest_path.write_text(json.dumps({"runs": sorted(runs, key=lambda r: r["run"])}, indent=1) + "\n")
    state_path.write_text(json.dumps({"last_success_at": now.isoformat()}, indent=2) + "\n")
    return {"result": "stored", "run": run.isoformat(), "values": int(len(frame))}


def available_runs(out: Path) -> list[Run]:
    return [Run(datetime.fromisoformat(r["run"]), datetime.fromisoformat(r["retrieved"]))
            for r in _load(out / ROOT / "manifest.json").get("runs", [])]


def load_run(out: Path, run: datetime) -> pd.DataFrame:
    """The stored response of one run, verified against its SHA-256, as the long table."""
    entry = next(r for r in _load(out / ROOT / "manifest.json")["runs"] if r["run"] == run.isoformat())
    body = gzip.decompress((out / ROOT / entry["file"]).read_bytes())
    if hashlib.sha256(body).hexdigest() != entry["sha256"]:
        raise WeatherSchemaError("stored weather payload altered")
    return parse(body)[0]
