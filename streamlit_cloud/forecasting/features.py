"""Weather predictor contract (Issue #57): variables, candidate points, as-of rules, ablations.

Status: CONTRACT ONLY. The project currently stores ICON wind speed/direction at 80/120 m for
the three farm sites. Temperature, precipitation, pressure, humidity and the western points
below are NOT collected: adding them is new upstream ingestion and needs a separate owner
decision. ``request_plan`` documents exactly what would be requested and how often.

Leakage rule: a model issued at ``issued_at`` may use an NWP run only if the run's
initialisation time AND the time it was actually retrieved (or provably available) are both
<= issued_at. Stitching short leads of many runs is not a faithful day-ahead input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

VARIABLES = (
    "wind_speed_80m", "wind_direction_80m", "wind_speed_120m", "wind_direction_120m", "wind_gusts_10m",
    "temperature_2m", "relative_humidity_2m", "precipitation", "rain", "pressure_msl", "surface_pressure",
    "cloud_cover",
)


@dataclass(frozen=True)
class Point:
    id: str
    lat: float
    lon: float
    region: str  # "west" | "central" | "east"
    role: str  # "upstream" | "target"


# Candidate points (to be validated against the chosen model's grid before any collection).
POINTS: tuple[Point, ...] = (
    Point("batumi", 41.64, 41.63, "west", "upstream"),
    Point("poti", 42.15, 41.67, "west", "upstream"),
    Point("kutaisi", 42.27, 42.70, "west", "upstream"),
    Point("surami_pass", 42.02, 43.55, "central", "upstream"),
    Point("gori_kartli", 41.98, 44.11, "east", "target"),
    Point("ruisi", 42.02, 44.03, "east", "target"),
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


def request_plan(runs_per_day: int = 4, forecast_hours: int = 72) -> dict:
    """What a future multi-point collection would request (not executed anywhere)."""
    return dict(points=len(POINTS), variables=len(VARIABLES), runs_per_day=runs_per_day,
                hours_per_run=forecast_hours, requests_per_day=runs_per_day,  # one batched call per run
                values_per_day=len(POINTS) * len(VARIABLES) * forecast_hours * runs_per_day,
                status="not active - needs owner approval (new upstream ingestion)")
