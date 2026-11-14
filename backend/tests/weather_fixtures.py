"""Recorded Open-Meteo responses and labelled derivations of them.

``real_archive_era5_3sites_20261106.json`` is an unmodified ERA5 archive response for the three
sites (Ruisi, Zemo Wind, Kartli), 2026-11-06..07, recorded 2026-11-14. ``FORECAST_LIKE`` is
derived from it by renaming the 100 m series to the forecast heights; it exercises the forecast
code path with real numbers and real structure and is clearly not a recorded forecast.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "openmeteo"
REAL_ARCHIVE_BYTES = (FIXTURES / "real_archive_era5_3sites_20261106.json").read_bytes()
REAL_ARCHIVE = json.loads(REAL_ARCHIVE_BYTES)
FIRST_T = 1793923200  # 2026-11-06T00:00Z
META_RUN_T = 1793923200 + 6 * 3600  # a run initialised at 06:00Z inside the fixture window


def forecast_like() -> list[dict]:
    data = copy.deepcopy(REAL_ARCHIVE)
    for loc in data:
        h, u = loc["hourly"], loc["hourly_units"]
        for height in (80, 120, 180):
            h[f"wind_speed_{height}m"] = list(h["wind_speed_100m"])
            h[f"wind_direction_{height}m"] = list(h["wind_direction_100m"])
            u[f"wind_speed_{height}m"] = "m/s"
            u[f"wind_direction_{height}m"] = "°"
        for k in ("wind_speed_100m", "wind_direction_100m"):
            h.pop(k)
            u.pop(k)
    return data


def meta(run_t: int = META_RUN_T) -> bytes:
    return json.dumps(
        {"last_run_initialisation_time": run_t, "last_run_availability_time": run_t + 10000}
    ).encode()
