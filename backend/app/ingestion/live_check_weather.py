"""Manual live verification of the Open-Meteo sources. Not part of CI; writes nothing.

Usage: python -m app.ingestion.live_check_weather
Exit code 0 only if both the forecast and the reanalysis request succeed and parse.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta

from app.config import get_settings
from app.ingestion.http_policy import FetchKind, fetch
from app.ingestion.openmeteo import (
    FORECAST,
    REANALYSIS,
    OpenMeteoError,
    archive_url,
    forecast_url,
    meta_url,
    parse_response,
    parse_run_time,
)
from app.ingestion.weather_job import build_weather_client
from app.sites import SITES
from app.timeutil import utcnow


def main() -> int:
    s = get_settings()
    now = utcnow()
    end = (now - timedelta(days=1)).date()
    start = end - timedelta(days=1)
    assert FORECAST.meta_model
    checks = {
        "forecast_run_meta": (meta_url(s.openmeteo_base_url, FORECAST.meta_model), None),
        "forecast": (forecast_url(s.openmeteo_base_url, SITES, 3), FORECAST.heights),
        "reanalysis": (
            archive_url(s.openmeteo_archive_base_url, SITES, start.isoformat(), end.isoformat()),
            REANALYSIS.heights,
        ),
    }
    report: dict[str, object] = {"checked_at": now.isoformat()}
    ok = True
    with build_weather_client(s) as client:
        for name, (url, heights) in checks.items():
            res = fetch(client, url, expect="json")
            entry: dict[str, object] = {
                "url": url,
                "outcome": res.kind.value,
                "http_status": res.status,
            }
            if res.retry_after is not None:
                entry["retry_after_s"] = int(res.retry_after.total_seconds())
            if res.kind is not FetchKind.OK:
                entry["body"] = res.body[:200].decode(errors="replace") if res.body else None
                ok = False
            else:
                try:
                    if heights is None:
                        entry["run_initialised_utc"] = parse_run_time(res.body).isoformat()
                    else:
                        series = parse_response(res.body, len(SITES), heights)
                        entry["sites"] = [
                            {
                                "site": site.id,
                                "grid": [
                                    loc.grid_latitude,
                                    loc.grid_longitude,
                                    loc.grid_elevation_m,
                                ],
                                "first_hour": {
                                    f"{h}m": [
                                        loc.by_height[h][0].valid_at.isoformat(),
                                        loc.by_height[h][0].speed_ms,
                                        loc.by_height[h][0].direction_deg,
                                    ]
                                    for h in heights
                                },
                            }
                            for site, loc in zip(SITES, series, strict=True)
                        ]
                except OpenMeteoError as exc:
                    entry["error"] = f"{exc.code}: {exc}"
                    ok = False
            report[name] = entry
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
