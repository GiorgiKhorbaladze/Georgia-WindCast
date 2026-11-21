"""Visual Crossing pilot source (Issue #57, owner decision 21.11.2026). Free tier, API key from the
repository secret VISUAL_CROSSING_API_KEY (never written to logs, files or the manifest).

Budget: one Timeline request per point per day (7 requests), 48 hourly values each = 336 records/day,
about 10,000 a month against the free 30,000. Visual Crossing blends several models: it is
evaluated as a separate source, not as an independent NWP model. The free tier has wind only at
10 m and no archive of past forecasts, so its evaluation relies on the runs stored here.

Stored like the other sources: forecast-data/weather/sources/visualcrossing/{manifest.json,
runs/<retrieval>.csv.gz}. Visual Crossing publishes no model run time, so the "run" is the
retrieval hour and the as-of rule uses the retrieval time.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

import pandas as pd

from forecasting.features import POINTS, RANGES, UNITS

BASE = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
ROOT = Path("weather") / "sources" / "visualcrossing"
ELEMENTS = "datetimeEpoch,temp,humidity,precip,pressure,cloudcover,windspeed,winddir,windgust"
MIN_INTERVAL = timedelta(hours=23)  # one collection a day
MAP = {"temp": "temperature_2m", "humidity": "relative_humidity_2m", "precip": "precipitation",
       "pressure": "pressure_msl", "cloudcover": "cloud_cover", "winddir": "wind_direction_10m"}


class VCError(ValueError):
    pass


def url(lat: float, lon: float, key: str) -> str:
    q = urlencode({"unitGroup": "metric", "include": "hours", "elements": ELEMENTS, "key": key,
                   "contentType": "json"})
    return f"{BASE}/{quote(f'{lat:.5f},{lon:.5f}')}/next2days?{q}"


def public_url(lat: float, lon: float) -> str:
    return url(lat, lon, "REDACTED")


def parse(point_id: str, body: bytes) -> list[tuple]:
    """Hourly rows; km/h wind converted to m/s; precipitation mm per hour; strict ranges."""
    data = json.loads(body)
    rows = []
    for day in data.get("days") or []:
        for h in day.get("hours") or []:
            t = pd.Timestamp(h["datetimeEpoch"], unit="s", tz="UTC")
            vals = {MAP[k]: float(h[k]) for k in MAP if h.get(k) is not None}
            if h.get("windspeed") is not None:
                vals["wind_speed_10m"] = float(h["windspeed"]) / 3.6
            if h.get("windgust") is not None:
                vals["wind_gusts_10m"] = float(h["windgust"]) / 3.6
            for var, v in vals.items():
                lo, hi = RANGES[UNITS[var]]
                if not lo <= v <= hi:
                    raise VCError(f"{point_id} {var}: {v} outside {lo}..{hi}")
                rows.append((point_id, t, var, round(v, 3)))
    if not rows:
        raise VCError(f"{point_id}: no hourly values")
    return rows


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def collect(out: Path, key: str | None, get: Callable[[str], tuple[int, bytes]], now: datetime,
            clock: Callable[[], datetime] | None = None) -> dict:
    if not key:
        return {"source": "visualcrossing", "result": "no_key"}
    root = out / ROOT
    manifest = _load(root / "manifest.json")
    runs = manifest.get("runs", [])
    if runs and now - datetime.fromisoformat(runs[-1]["retrieved"]) < MIN_INTERVAL:
        return {"source": "visualcrossing", "result": "not_due"}
    rows = []
    for p in POINTS:
        status, body = get(url(p.lat, p.lon, key))
        if status != 200:
            return {"source": "visualcrossing", "result": "failed", "error": f"http {status} at {p.id}"}
        rows += parse(p.id, body)
    df = pd.DataFrame(rows, columns=["point", "valid_utc", "variable", "value"])
    retrieved = (clock or (lambda: datetime.now(UTC).replace(microsecond=0)))()  # after the last response
    run = now.replace(minute=0, second=0, microsecond=0)
    csv = df.to_csv(index=False).encode()
    (root / "runs").mkdir(parents=True, exist_ok=True)
    name = f"{run:%Y%m%dT%H%MZ}.csv.gz"
    with gzip.GzipFile(root / "runs" / name, "wb", mtime=0) as fh:
        fh.write(csv)
    runs.append(dict(run=run.isoformat(), started=now.isoformat(), retrieved=retrieved.isoformat(), file=f"runs/{name}",
                     sha256=hashlib.sha256(csv).hexdigest(), values=int(len(df)), requests=len(POINTS),
                     url_template=public_url(0, 0)))
    (root / "manifest.json").write_text(json.dumps({"source": "visualcrossing", "runs": runs}, indent=1) + "\n")
    return {"source": "visualcrossing", "result": "stored", "values": int(len(df)), "requests": len(POINTS)}
