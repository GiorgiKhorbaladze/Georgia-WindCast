from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import WorkerHeartbeat
from app.schemas import (
    Freshness,
    GenerationLatest,
    SourceAttribution,
    SourceState,
    SourceStatus,
    SystemStatus,
    WorkerStatus,
)
from app.sites import SITES
from app.timeutil import utcnow

router = APIRouter(prefix="/api/v1", tags=["v1"])

GSE_ATTRIBUTION = SourceAttribution(
    name="Georgian State Electrosystem (GSE)", url="https://www.gse.com.ge"
)


@router.get("/generation/latest", response_model=GenerationLatest)
def generation_latest() -> GenerationLatest:
    """Latest national aggregate wind generation.

    GSE ingestion is not enabled yet (issue #3 validates the source first), so this endpoint
    honestly reports the value as unavailable rather than returning any placeholder number.
    """
    return GenerationLatest(
        freshness=Freshness.UNAVAILABLE,
        reason="ingestion_not_configured",
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


@router.get("/status", response_model=SystemStatus)
def system_status(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemStatus:
    return SystemStatus(
        generated_at=utcnow(),
        app_env=settings.app_env.value,
        worker=_worker_status(session, settings),
        sources=[
            SourceStatus(
                id="gse",
                state=SourceState.NOT_CONFIGURED,
                detail="Pending source verification (issue #3).",
            ),
            SourceStatus(
                id="open-meteo",
                state=SourceState.NOT_CONFIGURED,
                detail="Pending coordinate verification (issue #4).",
            ),
        ],
        sites=list(SITES),
    )
