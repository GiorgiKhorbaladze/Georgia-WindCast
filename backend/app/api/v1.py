from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.ingestion.gse_job import METRIC_WIND, PERIOD, SOURCE_ID
from app.models import GenerationReading, SourceStatusRecord, WorkerHeartbeat
from app.schemas import (
    Freshness,
    GenerationHistory,
    GenerationLatest,
    GenerationPoint,
    SourceAttribution,
    SourceState,
    SourceStatus,
    SystemStatus,
    TimeRange,
    WorkerStatus,
)
from app.sites import SITES
from app.timeutil import utcnow

router = APIRouter(prefix="/api/v1", tags=["v1"])

GSE_ATTRIBUTION = SourceAttribution(
    name="Georgian State Electrosystem (GSE)", url="https://www.gse.com.ge"
)
MAX_HISTORY_RANGE = timedelta(days=31)
GOOD_QUALITY = "ACT"
# A gap is reported when consecutive readings are further apart than this.
GAP_THRESHOLD = PERIOD * 1.5
# GSE publishes a period file 77-198 s after its label (observed). The most recent interval is
# not called a gap until this allowance has passed, otherwise every page load shows a false gap.
PUBLICATION_ALLOWANCE = timedelta(minutes=4)

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _wind_readings() -> Select[GenerationReading]:
    return select(GenerationReading).where(
        GenerationReading.source == SOURCE_ID, GenerationReading.metric == METRIC_WIND
    )


def _gse_status_row(session: Session) -> SourceStatusRecord | None:
    return session.get(SourceStatusRecord, SOURCE_ID)


@router.get("/generation/latest", response_model=GenerationLatest)
def generation_latest(session: SessionDep, settings: SettingsDep) -> GenerationLatest:
    """Latest national aggregate wind generation reported by GSE.

    Freshness is judged by the *source* period label, never by when we last polled, so a
    reading that GSE stopped updating turns stale even while polling continues.
    """
    latest = session.execute(
        _wind_readings().order_by(GenerationReading.period_label_at.desc()).limit(1)
    ).scalar_one_or_none()

    if latest is None:
        return GenerationLatest(
            freshness=Freshness.UNAVAILABLE,
            reason="ingestion_disabled" if not settings.gse_ingestion_enabled else "no_data_yet",
            source=GSE_ATTRIBUTION,
        )

    age = utcnow() - latest.period_label_at
    if age <= timedelta(seconds=settings.gse_fresh_within_seconds):
        freshness, reason = Freshness.FRESH, None
    else:
        freshness = Freshness.STALE
        status = _gse_status_row(session)
        if not settings.gse_ingestion_enabled:
            reason = "ingestion_disabled"
        elif status is not None and status.consecutive_failures > 0:
            reason = "source_unreachable"
        else:
            reason = "source_not_updated"

    return GenerationLatest(
        freshness=freshness,
        value_mw=latest.value_mw,
        source_observed_at=latest.period_label_at,
        retrieved_at=latest.retrieved_at,
        reason=reason,
        quality=latest.quality,
        quality_flagged=latest.quality != GOOD_QUALITY,
        period_seconds=int(PERIOD.total_seconds()),
        source=GSE_ATTRIBUTION,
    )


def compute_gaps(
    start: datetime, end: datetime, times: list[datetime], collection_started_at: datetime | None
) -> list[TimeRange]:
    """Intervals within [start, end] lacking readings, limited to the collection period.

    Time before collection began is not a "gap" in the source; it is simply not collected, and
    clients use ``collection_started_at`` to mark it.
    """
    if collection_started_at is None:
        return []
    lower = max(start, collection_started_at)
    gaps: list[TimeRange] = []
    cursor = lower
    for t in times:
        if t - cursor > GAP_THRESHOLD:
            gaps.append(TimeRange(start=cursor, end=t))
        cursor = max(cursor, t)
    if end - cursor > GAP_THRESHOLD and cursor < end:
        gaps.append(TimeRange(start=cursor, end=end))
    return gaps


@router.get("/generation/history", response_model=GenerationHistory)
def generation_history(
    session: SessionDep,
    start: Annotated[datetime | None, Query(description="UTC ISO 8601; default end - 24h")] = None,
    end: Annotated[datetime | None, Query(description="UTC ISO 8601; default now")] = None,
) -> GenerationHistory:
    """Collected actual readings only. Missing intervals are listed, never filled."""
    now = utcnow()
    end = end or now
    start = start or end - timedelta(hours=24)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "start and end must include a timezone offset")
    if start >= end:
        raise HTTPException(422, "start must be before end")
    if end - start > MAX_HISTORY_RANGE:
        raise HTTPException(422, f"range exceeds {MAX_HISTORY_RANGE.days} days")

    rows = session.execute(
        _wind_readings()
        .where(GenerationReading.period_label_at >= start, GenerationReading.period_label_at <= end)
        .order_by(GenerationReading.period_label_at)
    ).scalars()
    points = [
        GenerationPoint(t=r.period_label_at, value_mw=r.value_mw, quality=r.quality) for r in rows
    ]
    collection_started_at = session.execute(
        select(func.min(GenerationReading.period_label_at)).where(
            GenerationReading.source == SOURCE_ID, GenerationReading.metric == METRIC_WIND
        )
    ).scalar()
    return GenerationHistory(
        start=start,
        end=end,
        cadence_seconds=int(PERIOD.total_seconds()),
        collection_started_at=collection_started_at,
        points=points,
        gaps=compute_gaps(
            start,
            min(end, now - PUBLICATION_ALLOWANCE),
            [p.t for p in points],
            collection_started_at,
        ),
        source=GSE_ATTRIBUTION,
    )


def _worker_status(session: Session, settings: Settings) -> WorkerStatus:
    try:
        last_seen = session.execute(select(func.max(WorkerHeartbeat.last_seen_at))).scalar()
    except SQLAlchemyError:
        return WorkerStatus(state="never_seen", last_seen_at=None)
    if last_seen is None:
        return WorkerStatus(state="never_seen", last_seen_at=None)
    age = utcnow() - last_seen
    if age <= timedelta(seconds=settings.worker_stale_after_seconds):
        return WorkerStatus(state="running", last_seen_at=last_seen)
    return WorkerStatus(state="stale", last_seen_at=last_seen)


def _gse_source_status(session: Session, settings: Settings) -> SourceStatus:
    if not settings.gse_ingestion_enabled:
        return SourceStatus(
            id="gse",
            state=SourceState.NOT_CONFIGURED,
            detail="Ingestion disabled pending owner confirmation of reuse terms.",
        )
    row = _gse_status_row(session)
    state: SourceState
    detail: str | None
    if row is None or row.last_success_at is None:
        state, detail = SourceState.DEGRADED, "No successful fetch yet."
    elif row.consecutive_failures >= 3:
        state, detail = SourceState.DOWN, row.last_error
    elif row.consecutive_failures > 0:
        state, detail = SourceState.DEGRADED, row.last_error
    else:
        state, detail = SourceState.OK, None
    return SourceStatus(
        id="gse",
        state=state,
        detail=detail,
        last_attempt_at=row.last_attempt_at if row else None,
        last_success_at=row.last_success_at if row else None,
        consecutive_failures=row.consecutive_failures if row else 0,
        backoff_until=row.backoff_until if row else None,
    )


@router.get("/status", response_model=SystemStatus)
def system_status(session: SessionDep, settings: SettingsDep) -> SystemStatus:
    return SystemStatus(
        generated_at=utcnow(),
        app_env=settings.app_env.value,
        worker=_worker_status(session, settings),
        sources=[
            _gse_source_status(session, settings),
            SourceStatus(
                id="open-meteo",
                state=SourceState.NOT_CONFIGURED,
                detail="Pending coordinate verification (issue #4).",
            ),
        ],
        sites=list(SITES),
    )
