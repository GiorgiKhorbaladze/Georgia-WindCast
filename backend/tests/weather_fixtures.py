"""Recorded Open-Meteo responses and labelled derivations of them.

Unmodified recordings (2026-11-15 00:10 UTC, exact URLs built by app.ingestion.openmeteo):
- ``real_archive_era5_3sites_20261106.json``: ERA5 (models=era5), 3 sites, 2026-11-06..07.
- ``real_forecast_icon_global_3sites.json``: ICON global forecast, 3 sites, 4 days, run 18Z 14 Nov.
- ``real_meta_dwd_icon_before.json`` / ``_after.json``: run metadata fetched around the forecast
  (both report last_run_initialisation_time = 2026-11-14T18:00Z).

``forecast_like()`` is DERIVED from the archive recording (100 m series renamed to forecast
heights) only to test filtering of hours that precede a run, which the real forecast (starting after
its run) cannot exercise. It is clearly not a recorded forecast.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "openmeteo"
REAL_ARCHIVE_BYTES = (FIXTURES / "real_archive_era5_3sites_20261106.json").read_bytes()
REAL_ARCHIVE = json.loads(REAL_ARCHIVE_BYTES)
REAL_FORECAST_BYTES = (FIXTURES / "real_forecast_icon_global_3sites.json").read_bytes()
REAL_META_BYTES = (FIXTURES / "real_meta_dwd_icon_before.json").read_bytes()
REAL_RUN_T = json.loads(REAL_META_BYTES)["last_run_initialisation_time"]  # 2026-11-14T18:00Z
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
