"""Model weather API. Every value here is model-derived (m/s); none is a measurement."""

from __future__ import annotations

from dataclasses import dataclass
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


FORECAST_STEP = timedelta(hours=1)  # ICON global via Open-Meteo is hourly


@dataclass(frozen=True)
class SiteForwardCoverage:
    contiguous_end: datetime | None  # last hour of the unbroken run of usable hours from now
    last_valid_at: datetime | None  # last hour with data at every height (may follow gaps)
    missing_hours: int  # hours without data at every height between now and last_valid_at


def site_coverage_info(
    session: Session, run_at: datetime, now: datetime
) -> dict[str, SiteForwardCoverage]:
    """Usable forward coverage per site in one run.

    An hour counts only when every forecast height has a non-null speed for it. Coverage is the
    *contiguous* run of such hours starting at the current hour; a single missing hour ends it.
    Hours after the first gap are reported separately (last_valid_at, missing_hours), never as
    coverage.
    """
    start = _hour_floor(now)
    rows = session.execute(
        select(WeatherValue.site_id, WeatherValue.valid_at, func.count())
        .where(
            WeatherValue.product == FORECAST.product,
            WeatherValue.run_at == run_at,
            WeatherValue.speed_ms.is_not(None),
            WeatherValue.height_m.in_(FORECAST.heights),
            WeatherValue.valid_at >= start,
            WeatherValue.valid_at <= start + FORECAST_HORIZON,
        )
        .group_by(WeatherValue.site_id, WeatherValue.valid_at)
    ).all()
    complete: dict[str, set[datetime]] = {}
    for site_id, valid_at, n_heights in rows:
        if n_heights == len(FORECAST.heights):
            complete.setdefault(site_id, set()).add(valid_at)
    out: dict[str, SiteForwardCoverage] = {}
    for site in SITES:
        hours = complete.get(site.id, set())
        contiguous_end = None
        t = start
        while t in hours:
            contiguous_end = t
            t += FORECAST_STEP
        last = max(hours, default=None)
        missing = 0
        if last is not None:
            expected = int((last - start) / FORECAST_STEP) + 1
            missing = expected - len(hours)
        out[site.id] = SiteForwardCoverage(contiguous_end, last, missing)
    return out


def last_valid_any(session: Session, run_at: datetime) -> datetime | None:
    return session.execute(
        select(func.max(WeatherValue.valid_at)).where(
            WeatherValue.product == FORECAST.product,
            WeatherValue.run_at == run_at,
            WeatherValue.speed_ms.is_not(None),
        )
    ).scalar()


def _forward(end: datetime | None, now: datetime) -> timedelta:
    if end is None:
        return timedelta(0)
    # The hour labelled `end` is covered, so coverage extends to the end of that step.
    return max(timedelta(0), min(end + FORECAST_STEP, now + FORECAST_HORIZON) - now)


def forecast_coverage_state(
    now: datetime,
    run_at: datetime | None,
    coverage: dict[str, SiteForwardCoverage],
    last_valid: datetime | None,
    settings: Settings,
) -> tuple[Freshness, str | None, timedelta, datetime | None]:
    """Freshness requires a recent run AND contiguous forward coverage at every site.

    Returns (state, reason, aggregate forward coverage, aggregate contiguous horizon end).
    """
    if run_at is None:
        return Freshness.UNAVAILABLE, "no_forecast", timedelta(0), None
    if last_valid is None or last_valid < _hour_floor(now):
        return Freshness.UNAVAILABLE, "forecast_expired", timedelta(0), None
    ends = [c.contiguous_end for c in coverage.values()]
    if any(end is None for end in ends):
        state = Freshness.STALE if any(e is not None for e in ends) else Freshness.UNAVAILABLE
        return state, "incomplete_site_coverage", timedelta(0), None
    horizon = min(e for e in ends if e is not None)
    forward = _forward(horizon, now)
    if forward < timedelta(hours=settings.weather_min_forward_hours):
        return Freshness.STALE, "partial_coverage", forward, horizon
    if now - run_at > timedelta(seconds=settings.weather_fresh_within_seconds):
        return Freshness.STALE, "run_outdated", forward, horizon
    return Freshness.FRESH, None, forward, horizon


@router.get("", response_model=WeatherOverview)
def weather_overview(session: SessionDep, settings: SettingsDep) -> WeatherOverview:
    now = utcnow()
    run_at = latest_run(session)
    now_rows: list[WeatherNow] = []
    retrieved_at = horizon_end = None
    coverage: dict[str, SiteForwardCoverage] = {}
    last_valid: datetime | None = None
    if run_at is not None:
        retrieved_at = session.execute(
            select(func.max(WeatherValue.retrieved_at)).where(
                WeatherValue.product == FORECAST.product, WeatherValue.run_at == run_at
            )
        ).scalar()
        coverage = site_coverage_info(session, run_at, now)
        last_valid = last_valid_any(session, run_at)
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
    state, reason, forward, horizon_end = forecast_coverage_state(
        now, run_at, coverage, last_valid, settings
    )
    site_coverage = [
        SiteCoverage(
            site_id=site.id,
            horizon_end=(c.contiguous_end + FORECAST_STEP) if c and c.contiguous_end else None,
            forward_hours=round(
                _forward(c.contiguous_end if c else None, now).total_seconds() / 3600, 1
            ),
            last_valid_at=c.last_valid_at if c else None,
            missing_hours=c.missing_hours if c else 0,
        )
        for site in SITES
        for c in [coverage.get(site.id)]
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
        forecast_horizon_end=(
            min(horizon_end + FORECAST_STEP, now + FORECAST_HORIZON) if horizon_end else None
        ),
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
