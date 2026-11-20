"""Weather predictor contract (Issue #57): variables, candidate points, as-of rules, ablations.

Collection (owner-approved 20.11.2026): forecasting/weather_points.py requests these variables at
POINTS in ONE batched Open-Meteo call per new ICON run (the run the GSE collector already
detected), so there is no extra polling and no duplicate per-point request.

Leakage rule: a model issued at ``issued_at`` may use an NWP run only if the run's
initialisation time AND the time it was actually retrieved (or provably available) are both
<= issued_at. Stitching short leads of many runs is not a faithful day-ahead input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "precipitation", "rain", "pressure_msl", "surface_pressure",
    "cloud_cover", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "wind_speed_80m",
    "wind_direction_80m", "wind_speed_120m", "wind_direction_120m",
)
# Expected units in the provider response; anything else is refused (schema drift).
UNITS = {"temperature_2m": "°C", "relative_humidity_2m": "%", "precipitation": "mm", "rain": "mm",
         "pressure_msl": "hPa", "surface_pressure": "hPa", "cloud_cover": "%", "wind_speed_10m": "m/s",
         "wind_direction_10m": "°", "wind_gusts_10m": "m/s", "wind_speed_80m": "m/s", "wind_direction_80m": "°",
         "wind_speed_120m": "m/s", "wind_direction_120m": "°"}
RANGES = {"°C": (-60, 60), "%": (0, 100), "mm": (0, 300), "hPa": (500, 1100), "m/s": (0, 100), "°": (0, 360)}


@dataclass(frozen=True)
class Point:
    id: str
    lat: float
    lon: float
    region: str  # "west" | "central" | "east"
    role: str  # "upstream" | "target"


# Points requested in one batched call per ICON run (forecasting/weather_points.py). The farm points
# reuse the verified site coordinates (backend/app/sites.py); Ruisi shares Kartli's ICON cell
# (42.0, 44.0) and is therefore not requested twice.
POINTS: tuple[Point, ...] = (
    Point("batumi", 41.64, 41.63, "west", "upstream"),
    Point("poti", 42.15, 41.67, "west", "upstream"),
    Point("kutaisi", 42.27, 42.70, "west", "upstream"),
    Point("surami_pass", 42.02, 43.55, "central", "upstream"),
    Point("kartli_ruisi", 42.022423, 44.047890, "east", "target"),
    Point("zemo", 41.895560, 44.370612, "east", "target"),
    Point("tbilisi", 41.72, 44.79, "east", "target"),
)

ABLATIONS = {
    "local_wind": {"regions": ("east",), "variables": ("wind_speed_80m", "wind_speed_120m", "wind_direction_80m")},
    "local_weather": {"regions": ("east",), "variables": VARIABLES},
    "local_plus_west": {"regions": ("east", "central", "west"), "variables": VARIABLES},
}


@dataclass(frozen=True)
class Run:
    run_utc: datetime  # model initialisation
    retrieved_utc: datetime  # when the project actually obtained it


def asof(runs: list[Run], issued_at: datetime) -> Run | None:
    """Newest run that was both initialised and obtained by ``issued_at``."""
    ok = [r for r in runs if r.run_utc <= issued_at and r.retrieved_utc <= issued_at]
    return max(ok, key=lambda r: r.run_utc) if ok else None


def air_density(pressure_hpa: float, temperature_c: float, rh_percent: float | None = None) -> float:
    """kg/m^3 from p/(R_d*T_v); virtual temperature when humidity is given (Tetens vapour pressure)."""
    t_k = temperature_c + 273.15
    p_pa = pressure_hpa * 100.0
    if rh_percent is not None:
        e = rh_percent / 100.0 * 610.94 * math.exp(17.625 * temperature_c / (temperature_c + 243.04))
        t_k = t_k / (1 - 0.378 * e / p_pa)
    return p_pa / (287.05 * t_k)


def pressure_gradient(west_hpa: float, east_hpa: float) -> float:
    """West-minus-east sea-level pressure difference (hPa); sign convention fixed here."""
    return west_hpa - east_hpa


def request_plan(runs_per_day: int = 4, forecast_days: int = 4) -> dict:
    """Request budget of the batched collection (one data call + two metadata checks per new run).

    ``weighted_calls_*`` is an ESTIMATE assuming Open-Meteo counts each location, and each block of
    10 variables, as one call; the free tier allows 10,000 calls per day."""
    per_request = len(POINTS) * math.ceil(len(VARIABLES) / 10)
    return dict(points=len(POINTS), variables=len(VARIABLES), runs_per_day=runs_per_day,
                forecast_days=forecast_days, http_requests_per_day=runs_per_day * 3,
                weighted_calls_per_request_estimate=per_request,
                weighted_calls_per_day_estimate=runs_per_day * (per_request + 2),
                status="active once per new ICON run (owner-approved 20.11.2026)")
