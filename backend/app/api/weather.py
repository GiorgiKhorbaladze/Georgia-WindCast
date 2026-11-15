"""Model weather API. Every value here is model-derived (m/s); none is a measurement."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.ingestion.openmeteo import (
    ALL_HEIGHTS,
    FORECAST,
    PRODUCTS,
    REANALYSIS,
    UNSUPPORTED_HEIGHTS,
    ProductSpec,
)
from app.ingestion.weather_job import PROVIDER, REANALYSIS_RUN_REF
from app.models import WeatherValue
from app.schemas import (
    Freshness,
    SiteCoverage,
    SiteWeather,
    SourceAttribution,
    WeatherNow,
    WeatherOverview,
    WeatherPoint,
    WeatherProduct,
    WeatherSeries,
)
from app.sites import SITES, SITES_BY_ID
from app.timeutil import utcnow

router = APIRouter(prefix="/api/v1/weather", tags=["weather"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

ATTRIBUTION = [
    SourceAttribution(
        name="Weather data by Open-Meteo.com (CC BY 4.0)", url="https://open-meteo.com/"
    ),
    SourceAttribution(name="DWD ICON model (Deutscher Wetterdienst)", url="https://www.dwd.de/"),
    SourceAttribution(
        name="ERA5 reanalysis (ECMWF / Copernicus)", url="https://cds.climate.copernicus.eu/"
    ),
]
FORECAST_HORIZON = timedelta(hours=72)
MAX_RANGE = timedelta(days=31)


def latest_run(session: Session) -> datetime | None:
    return session.execute(
        select(func.max(WeatherValue.run_at)).where(
            WeatherValue.product == FORECAST.product, WeatherValue.model == FORECAST.model
        )
    ).scalar()


def _hour_floor(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def _series(
    spec: ProductSpec,
    height: int,
    rows: list[WeatherValue],
    run_at: datetime | None,
) -> WeatherSeries:
    first = rows[0] if rows else None
    provenance: Literal["single_run", "mixed_runs", "reanalysis", "none"]
    if spec.product == REANALYSIS.product:
        provenance = "reanalysis" if rows else "none"
    else:
        runs = {r.run_at for r in rows}
        if not rows:
            provenance = "none"
        elif len(runs) == 1:
            provenance, run_at = "single_run", next(iter(runs))
        else:
            # Several runs contribute: no single run time is claimed for the series.
            provenance, run_at = "mixed_runs", None
    return WeatherSeries(
        product=WeatherProduct(spec.product),
        provider=PROVIDER,
        model=spec.model,
        model_label=spec.label,
        height_m=height,
        run_at=run_at,
        retrieved_at=max((r.retrieved_at for r in rows), default=None),
        grid_latitude=first.grid_latitude if first else None,
        grid_longitude=first.grid_longitude if first else None,
        grid_elevation_m=first.grid_elevation_m if first else None,
        supported=height in spec.heights,
        provenance=provenance,
        points=[
            WeatherPoint(
                t=r.valid_at, speed_ms=r.speed_ms, direction_deg=r.direction_deg, run_at=r.run_at
            )
            for r in rows
        ],
    )


def site_horizons(session: Session, run_at: datetime) -> dict[str, datetime | None]:
    """Per site: the last valid time covered at every forecast height in the given run."""
    rows = session.execute(
        select(WeatherValue.site_id, WeatherValue.height_m, func.max(WeatherValue.valid_at))
        .where(
            WeatherValue.product == FORECAST.product,
            WeatherValue.run_at == run_at,
            WeatherValue.speed_ms.is_not(None),
        )
        .group_by(WeatherValue.site_id, WeatherValue.height_m)
    ).all()
    per_site: dict[str, dict[int, datetime]] = {}
    for site_id, height, end in rows:
        per_site.setdefault(site_id, {})[height] = end
    out: dict[str, datetime | None] = {}
    for site in SITES:
        heights = per_site.get(site.id, {})
        out[site.id] = (
            min(heights[h] for h in FORECAST.heights)
            if all(h in heights for h in FORECAST.heights)
            else None
        )
    return out


def forecast_coverage_state(
    now: datetime, run_at: datetime | None, horizon_end: datetime | None, settings: Settings
) -> tuple[Freshness, str | None, timedelta]:
    """Freshness requires usable forward coverage, not just a recent run."""
    if run_at is None:
        return Freshness.UNAVAILABLE, "no_forecast", timedelta(0)
    if horizon_end is None:
        # A run exists but no tracked site is covered at every forecast height.
        return Freshness.UNAVAILABLE, "incomplete_site_coverage", timedelta(0)
    forward = min(horizon_end, now + FORECAST_HORIZON) - now
    if forward <= timedelta(0):
        return Freshness.UNAVAILABLE, "forecast_expired", timedelta(0)
    if forward < timedelta(hours=settings.weather_min_forward_hours):
        return Freshness.STALE, "partial_coverage", forward
    if now - run_at > timedelta(seconds=settings.weather_fresh_within_seconds):
        return Freshness.STALE, "run_outdated", forward
    return Freshness.FRESH, None, forward


@router.get("", response_model=WeatherOverview)
def weather_overview(session: SessionDep, settings: SettingsDep) -> WeatherOverview:
    now = utcnow()
    run_at = latest_run(session)
    now_rows: list[WeatherNow] = []
    retrieved_at = horizon_end = None
    site_ends: dict[str, datetime | None] = {site.id: None for site in SITES}
    if run_at is not None:
        retrieved_at = session.execute(
            select(func.max(WeatherValue.retrieved_at)).where(
                WeatherValue.product == FORECAST.product, WeatherValue.run_at == run_at
            )
        ).scalar()
        site_ends = site_horizons(session, run_at)
        covered = [end for end in site_ends.values() if end is not None]
        # The aggregate horizon is the most conservative one: what EVERY site has.
        horizon_end = min(covered) if len(covered) == len(SITES) else max(covered, default=None)
        hour = _hour_floor(now)
        current = {
            (r.site_id, r.height_m): r
            for r in session.execute(
                select(WeatherValue).where(
                    WeatherValue.product == FORECAST.product,
                    WeatherValue.run_at == run_at,
                    WeatherValue.valid_at == hour,
                )
            ).scalars()
        }
    else:
        current = {}
    for site in SITES:
        for h in FORECAST.heights:
            r = current.get((site.id, h))
            now_rows.append(
                WeatherNow(
                    site_id=site.id,
                    height_m=h,
                    valid_at=r.valid_at if r else None,
                    speed_ms=r.speed_ms if r else None,
                    direction_deg=r.direction_deg if r else None,
                    model=FORECAST.model if r else None,
                    run_at=run_at if r else None,
                )
            )
    state, reason, forward = forecast_coverage_state(now, run_at, horizon_end, settings)
    incomplete = run_at is not None and any(end is None or end <= now for end in site_ends.values())
    if incomplete and state is not Freshness.UNAVAILABLE:
        # At least one tracked site has no forward coverage: never report the aggregate as fresh.
        state, reason, forward = Freshness.STALE, "incomplete_site_coverage", timedelta(0)
    if state is Freshness.UNAVAILABLE:
        horizon_end = None
    site_coverage = [
        SiteCoverage(
            site_id=site_id,
            horizon_end=end if end is not None and end > now else None,
            forward_hours=round(
                max(timedelta(0), min(end, now + FORECAST_HORIZON) - now).total_seconds() / 3600, 1
            )
            if end is not None
            else 0.0,
        )
        for site_id, end in site_ends.items()
    ]
    return WeatherOverview(
        generated_at=now,
        heights={name: list(spec.heights) for name, spec in PRODUCTS.items()},
        unsupported_heights=list(UNSUPPORTED_HEIGHTS),
        forecast_model=FORECAST.model,
        forecast_model_label=FORECAST.label,
        forecast_state=state,
        forecast_reason=reason,
        forecast_forward_hours=round(forward.total_seconds() / 3600, 1),
        site_coverage=site_coverage,
        forecast_run_at=run_at,
        forecast_retrieved_at=retrieved_at,
        forecast_horizon_end=min(horizon_end, now + FORECAST_HORIZON) if horizon_end else None,
        sites=list(SITES),
        now=now_rows,
        attribution=ATTRIBUTION,
    )


@router.get("/sites/{site_id}", response_model=SiteWeather)
def site_weather(
    session: SessionDep,
    site_id: Annotated[str, Path()],
    height: Annotated[int, Query(description="Height above ground, m")] = 100,
    start: Annotated[datetime | None, Query(description="UTC ISO 8601; default now - 48 h")] = None,
    end: Annotated[datetime | None, Query(description="UTC ISO 8601; default now")] = None,
) -> SiteWeather:
    site = SITES_BY_ID.get(site_id)
    if site is None:
        raise HTTPException(404, "unknown site")
    if height not in ALL_HEIGHTS:
        raise HTTPException(422, f"height must be one of {list(ALL_HEIGHTS)}")
    now = utcnow()
    end = end or now
    start = start or end - timedelta(hours=48)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "start and end must include a timezone offset")
    if start >= end:
        raise HTTPException(422, "start must be before end")
    if end - start > MAX_RANGE:
        raise HTTPException(422, f"range exceeds {MAX_RANGE.days} days")
    past_end = min(end, now)

    # History: for each past hour, the value from the most recent run issued at or before it
    # (i.e. the shortest-lead forecast available). Gaps stay gaps.
    history_rows = list(
        session.execute(
            select(WeatherValue)
            .where(
                WeatherValue.site_id == site_id,
                WeatherValue.product == FORECAST.product,
                WeatherValue.model == FORECAST.model,
                WeatherValue.height_m == height,
                WeatherValue.valid_at >= start,
                WeatherValue.valid_at < past_end,
                WeatherValue.run_at <= WeatherValue.valid_at,
            )
            .order_by(WeatherValue.valid_at, WeatherValue.run_at.desc())
            .ext(distinct_on(WeatherValue.valid_at))
        ).scalars()
    )
    run_at = latest_run(session)
    forecast_rows: list[WeatherValue] = []
    if run_at is not None:
        forecast_rows = list(
            session.execute(
                select(WeatherValue)
                .where(
                    WeatherValue.site_id == site_id,
                    WeatherValue.product == FORECAST.product,
                    WeatherValue.run_at == run_at,
                    WeatherValue.height_m == height,
                    WeatherValue.valid_at >= _hour_floor(now),
                    WeatherValue.valid_at <= now + FORECAST_HORIZON,
                )
                .order_by(WeatherValue.valid_at)
            ).scalars()
        )
    reanalysis_rows = list(
        session.execute(
            select(WeatherValue)
            .where(
                WeatherValue.site_id == site_id,
                WeatherValue.product == REANALYSIS.product,
                WeatherValue.run_ref == REANALYSIS_RUN_REF,
                WeatherValue.height_m == height,
                WeatherValue.valid_at >= start,
                WeatherValue.valid_at <= past_end,
            )
            .order_by(WeatherValue.valid_at)
        ).scalars()
    )
    return SiteWeather(
        site=site,
        height_m=height,
        history=_series(FORECAST, height, history_rows, None),
        forecast=_series(FORECAST, height, forecast_rows, run_at),
        reanalysis=_series(REANALYSIS, height, reanalysis_rows, None),
        attribution=ATTRIBUTION,
    )
