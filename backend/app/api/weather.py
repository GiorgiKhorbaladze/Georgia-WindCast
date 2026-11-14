"""Model weather API. Every value here is model-derived (m/s); none is a measurement."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

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
        points=[
            WeatherPoint(t=r.valid_at, speed_ms=r.speed_ms, direction_deg=r.direction_deg)
            for r in rows
        ],
    )


@router.get("", response_model=WeatherOverview)
def weather_overview(session: SessionDep, settings: SettingsDep) -> WeatherOverview:
    now = utcnow()
    run_at = latest_run(session)
    now_rows: list[WeatherNow] = []
    retrieved_at = horizon_end = None
    if run_at is not None:
        agg = session.execute(
            select(func.max(WeatherValue.retrieved_at), func.max(WeatherValue.valid_at)).where(
                WeatherValue.product == FORECAST.product, WeatherValue.run_at == run_at
            )
        ).one()
        retrieved_at, horizon_end = agg
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
    if run_at is None:
        state = Freshness.UNAVAILABLE
    elif now - run_at <= timedelta(seconds=settings.weather_fresh_within_seconds):
        state = Freshness.FRESH
    else:
        state = Freshness.STALE
    return WeatherOverview(
        generated_at=now,
        heights={name: list(spec.heights) for name, spec in PRODUCTS.items()},
        unsupported_heights=list(UNSUPPORTED_HEIGHTS),
        forecast_model=FORECAST.model,
        forecast_model_label=FORECAST.label,
        forecast_state=state,
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
    history_run = max((r.run_at for r in history_rows if r.run_at), default=None)
    return SiteWeather(
        site=site,
        height_m=height,
        history=_series(FORECAST, height, history_rows, history_run),
        forecast=_series(FORECAST, height, forecast_rows, run_at),
        reanalysis=_series(REANALYSIS, height, reanalysis_rows, None),
        attribution=ATTRIBUTION,
    )
