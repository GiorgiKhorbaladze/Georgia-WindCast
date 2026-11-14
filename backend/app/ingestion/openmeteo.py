"""Open-Meteo request building and strict response parsing.

Verified behaviour (2026-11-14, see docs/sources/weather.md):
- Several coordinates can be requested at once (comma-separated); the response is then a JSON list
  in request order. A single coordinate returns an object.
- ``wind_speed_unit=ms`` yields ``"m/s"`` units; directions are in degrees (meteorological, FROM).
- Forecast API heights: 10, 80, 120, 180 m. Archive (ERA5) heights: 10 and 100 m. No product offers
  200 m; it is reported as unsupported, never interpolated.
- ``/data/<model>/static/meta.json`` publishes ``last_run_initialisation_time`` (unix seconds).
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlencode

from app.schemas import SiteSummary


class OpenMeteoError(ValueError):
    code = "schema_drift"


@dataclass(frozen=True, slots=True)
class ProductSpec:
    product: str  # "forecast" | "reanalysis"
    model: str  # Open-Meteo ``models=`` value
    meta_model: str | None  # path segment for /data/<x>/static/meta.json, if published
    label: str
    heights: tuple[int, ...]


FORECAST = ProductSpec(
    product="forecast",
    model="icon_global",
    meta_model="dwd_icon",
    label="DWD ICON global (~13 km) via Open-Meteo",
    heights=(10, 80, 120, 180),
)
REANALYSIS = ProductSpec(
    product="reanalysis",
    model="era5",
    meta_model=None,
    label="ECMWF ERA5 reanalysis (~25 km) via Open-Meteo",
    heights=(10, 100),
)
PRODUCTS = {p.product: p for p in (FORECAST, REANALYSIS)}
ALL_HEIGHTS = (10, 80, 100, 120, 180, 200)
UNSUPPORTED_HEIGHTS = tuple(
    h for h in ALL_HEIGHTS if not any(h in p.heights for p in PRODUCTS.values())
)
MAX_PLAUSIBLE_SPEED_MS = 120.0


def hourly_variables(heights: Sequence[int]) -> list[str]:
    out: list[str] = []
    for h in heights:
        out += [f"wind_speed_{h}m", f"wind_direction_{h}m"]
    return out


def _coords(sites: Sequence[SiteSummary]) -> dict[str, str]:
    lats, lons = [], []
    for s in sites:
        if not s.coordinates_verified or s.latitude is None or s.longitude is None:
            raise ValueError(f"site {s.id} has no verified coordinates")
        lats.append(f"{s.latitude:.6f}")
        lons.append(f"{s.longitude:.6f}")
    return {"latitude": ",".join(lats), "longitude": ",".join(lons)}


def forecast_url(base: str, sites: Sequence[SiteSummary], forecast_days: int) -> str:
    params = {
        **_coords(sites),
        "hourly": ",".join(hourly_variables(FORECAST.heights)),
        "models": FORECAST.model,
        "forecast_days": str(forecast_days),
        "wind_speed_unit": "ms",
        "timeformat": "unixtime",
        "timezone": "GMT",
    }
    return f"{base.rstrip('/')}/v1/forecast?{urlencode(params, safe=',')}"


def archive_url(base: str, sites: Sequence[SiteSummary], start: str, end: str) -> str:
    params = {
        **_coords(sites),
        "hourly": ",".join(hourly_variables(REANALYSIS.heights)),
        "models": REANALYSIS.model,
        "start_date": start,
        "end_date": end,
        "wind_speed_unit": "ms",
        "timeformat": "unixtime",
        "timezone": "GMT",
    }
    return f"{base.rstrip('/')}/v1/archive?{urlencode(params, safe=',')}"


def meta_url(base: str, meta_model: str) -> str:
    return f"{base.rstrip('/')}/data/{meta_model}/static/meta.json"


@dataclass(frozen=True, slots=True)
class HourValue:
    valid_at: datetime
    speed_ms: float | None
    direction_deg: float | None


@dataclass
class LocationSeries:
    grid_latitude: float
    grid_longitude: float
    grid_elevation_m: float | None
    by_height: dict[int, list[HourValue]] = field(default_factory=dict)


def _num(value: object, *, what: str, lo: float, hi: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OpenMeteoError(f"{what}: non-numeric value {value!r}")
    v = float(value)
    if not math.isfinite(v) or not lo <= v <= hi:
        raise OpenMeteoError(f"{what}: out-of-range value {v}")
    return v


def parse_response(
    payload: bytes, n_locations: int, heights: Sequence[int]
) -> list[LocationSeries]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OpenMeteoError(f"not JSON: {exc}") from exc
    if isinstance(data, dict) and data.get("error"):
        raise OpenMeteoError(f"provider error: {str(data.get('reason'))[:200]}")
    items = data if isinstance(data, list) else [data]
    if len(items) != n_locations:
        raise OpenMeteoError(f"expected {n_locations} locations, got {len(items)}")

    out: list[LocationSeries] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise OpenMeteoError(f"location {idx}: not an object")
        hourly = item.get("hourly")
        units = item.get("hourly_units")
        if not isinstance(hourly, dict) or not isinstance(units, dict):
            raise OpenMeteoError(f"location {idx}: missing hourly data")
        if units.get("time") != "unixtime":
            raise OpenMeteoError(f"location {idx}: unexpected time format {units.get('time')!r}")
        times = hourly.get("time")
        if not isinstance(times, list) or not times:
            raise OpenMeteoError(f"location {idx}: missing time axis")
        stamps = [datetime.fromtimestamp(int(t), UTC) for t in times]
        series = LocationSeries(
            grid_latitude=float(item["latitude"]),
            grid_longitude=float(item["longitude"]),
            grid_elevation_m=_num(item.get("elevation"), what="elevation", lo=-500, hi=9000),
        )
        for h in heights:
            sk, dk = f"wind_speed_{h}m", f"wind_direction_{h}m"
            if sk not in hourly or dk not in hourly:
                raise OpenMeteoError(f"location {idx}: missing {sk}/{dk}")
            if units.get(sk) != "m/s":
                raise OpenMeteoError(f"location {idx}: {sk} unit {units.get(sk)!r}, expected m/s")
            if units.get(dk) not in ("°", "deg"):
                raise OpenMeteoError(f"location {idx}: {dk} unit {units.get(dk)!r}")
            speeds, dirs = hourly[sk], hourly[dk]
            if len(speeds) != len(stamps) or len(dirs) != len(stamps):
                raise OpenMeteoError(f"location {idx}: {sk}/{dk} length mismatch")
            values = []
            for t, sp, di in zip(stamps, speeds, dirs, strict=True):
                speed = _num(sp, what=sk, lo=0.0, hi=MAX_PLAUSIBLE_SPEED_MS)
                direction = _num(di, what=dk, lo=0.0, hi=360.0)
                values.append(HourValue(t, speed, direction))
            series.by_height[h] = values
        out.append(series)
    return out


def parse_run_time(payload: bytes) -> datetime:
    try:
        data = json.loads(payload)
        ts = data["last_run_initialisation_time"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise OpenMeteoError("meta.json without last_run_initialisation_time") from exc
    if not isinstance(ts, int) or ts <= 0:
        raise OpenMeteoError(f"invalid run time {ts!r}")
    return datetime.fromtimestamp(ts, UTC)
