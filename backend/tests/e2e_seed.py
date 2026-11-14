"""Seed a TEST database for browser end-to-end tests. Never for production.

Refuses to run unless WINDCAST_APP_ENV=test. It is not part of any container image (tests/ is
excluded by .dockerignore).

Content, so the UI can be exercised in populated states:
- Generation: the 14 real GSE wind values collected live on 2026-11-14 19:42-20:21 UTC
  (docs/evidence/gse/live-e2e.txt), re-timestamped to end 3 minutes before "now". The original
  qualities are kept (including NRE). A deliberate 15-minute gap tests gap rendering.
- Weather: values from the recorded ERA5 archive fixture (real numbers), re-timestamped and used as
  a forecast run (heights 10/80/120/180) and as reanalysis (10/100), so all chart series appear.

Scenarios (UI states for issue #5): default = fresh; --stale = all readings shifted 2 h into the
past; --zero = the latest reading is a real 0.0 MW value (calm); --clear = empty database.

Usage:
  WINDCAST_APP_ENV=test WINDCAST_DATABASE_URL=... python -m tests.e2e_seed [--clear|--stale|--zero]
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete

from app.db import get_sessionmaker
from app.models import GenerationReading, SourceStatusRecord, WeatherValue
from app.sites import SITES
from app.timeutil import utcnow

REAL_GSE = [
    (101.837883, "NRE"),
    (103.058807, "ACT"),
    (103.115593, "NRE"),
    (97.372612, "ACT"),
    (92.778778, "ACT"),
    (93.40934, "ACT"),
    (92.930557, "ACT"),
    (91.333824, "NRE"),
    (85.93499, "ACT"),
    (73.599297, "ACT"),
    (73.599297, "ACT"),
    (72.440331, "NRE"),
    (74.529854, "ACT"),
    (79.686813, "ACT"),
]
ARCHIVE = (
    Path(__file__).parent / "fixtures" / "openmeteo" / "real_archive_era5_3sites_20261106.json"
)


def main() -> int:
    if os.environ.get("WINDCAST_APP_ENV") != "test":
        print("refusing: WINDCAST_APP_ENV must be 'test'", file=sys.stderr)
        return 2
    if "--clear" in sys.argv:
        with get_sessionmaker()() as s, s.begin():
            for model in (GenerationReading, WeatherValue, SourceStatusRecord):
                s.execute(delete(model))
        print("cleared e2e data")
        return 0
    now = utcnow().replace(second=0, microsecond=0)
    latest = now - timedelta(minutes=3 + now.minute % 3)
    if "--stale" in sys.argv:
        latest -= timedelta(hours=2)
    readings = list(REAL_GSE)
    if "--zero" in sys.argv:
        readings[-1] = (0.0, "ACT")  # synthetic calm value for the zero-state test only
    archive = json.loads(ARCHIVE.read_text()) if ARCHIVE.exists() else None
    if archive is None:
        print(f"WARNING: {ARCHIVE.name} missing; weather not seeded", file=sys.stderr)
    hour = now.replace(minute=0)
    run_at = hour - timedelta(hours=3)

    with get_sessionmaker()() as s, s.begin():
        s.execute(delete(GenerationReading))
        s.execute(delete(WeatherValue))
        s.execute(delete(SourceStatusRecord))
        n = len(readings)
        for i, (value, quality) in enumerate(readings):
            t = latest - timedelta(minutes=3 * (n - 1 - i))
            if i < 5:
                t -= timedelta(minutes=15)  # deliberate gap between the 5th and 6th reading
            s.add(
                GenerationReading(
                    source="gse",
                    metric="wind_total",
                    period_label_at=t,
                    period_label_local="e2e-seed",
                    value_mw=value,
                    quality=quality,
                    source_url="e2e-seed://docs/evidence/gse/live-e2e.txt",
                    payload_sha256="0" * 64,
                    parser_version="e2e-seed",
                    retrieved_at=t + timedelta(seconds=80),
                )
            )
        for site, loc in zip(SITES, archive or [], strict=archive is not None):
            speeds, dirs10 = loc["hourly"]["wind_speed_100m"], loc["hourly"]["wind_direction_100m"]
            sp10 = loc["hourly"]["wind_speed_10m"]
            for k in range(48):
                valid = run_at - timedelta(hours=24) + timedelta(hours=k)
                for h, factor in ((10, None), (80, 0.95), (120, 1.05), (180, 1.12)):
                    sp = sp10[k] if factor is None else round(speeds[k] * factor, 2)
                    for rr, ra in (
                        (run_at - timedelta(hours=6), run_at - timedelta(hours=6)),
                        (run_at, run_at),
                    ):
                        if valid < ra:
                            continue
                        s.add(
                            WeatherValue(
                                site_id=site.id,
                                product="forecast",
                                provider="open-meteo",
                                model="icon_global",
                                run_ref=rr.isoformat(),
                                run_at=ra,
                                valid_at=valid,
                                height_m=h,
                                speed_ms=sp,
                                direction_deg=dirs10[k],
                                grid_latitude=loc["latitude"],
                                grid_longitude=loc["longitude"],
                                grid_elevation_m=loc["elevation"],
                                retrieved_at=ra + timedelta(hours=3),
                            )
                        )
                if valid < now - timedelta(hours=6):
                    for h, series in ((10, sp10), (100, speeds)):
                        s.add(
                            WeatherValue(
                                site_id=site.id,
                                product="reanalysis",
                                provider="open-meteo",
                                model="era5",
                                run_ref="era5",
                                run_at=None,
                                valid_at=valid,
                                height_m=h,
                                speed_ms=series[k],
                                direction_deg=dirs10[k],
                                grid_latitude=loc["latitude"],
                                grid_longitude=loc["longitude"],
                                grid_elevation_m=loc["elevation"],
                                retrieved_at=now,
                            )
                        )
    print(f"seeded e2e data at {now.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
