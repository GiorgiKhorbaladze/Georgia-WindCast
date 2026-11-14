from __future__ import annotations

from typing import Annotated

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.migrations import alembic_config
from app.schemas import HealthResponse, ReadinessResponse
from app.version import __version__

router = APIRouter(prefix="/api/health", tags=["health"])


def _migration_head(cfg: Config) -> str | None:
    return ScriptDirectory.from_config(cfg).get_current_head()


@router.get("", response_model=HealthResponse)
def liveness() -> HealthResponse:
    """Process liveness. Does not touch the database."""
    return HealthResponse(status="ok", service="windcast-api", version=__version__)


@router.get("/ready", response_model=ReadinessResponse)
def readiness(
    response: Response, session: Annotated[Session, Depends(get_session)]
) -> ReadinessResponse:
    """Ready only when the database is reachable and fully migrated."""
    head = _migration_head(alembic_config())
    try:
        session.execute(text("SELECT 1"))
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            database="error",
            migration_revision=None,
            migration_head=head,
            detail=type(exc).__name__,
        )
    if revision != head:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            database="ok",
            migration_revision=revision,
            migration_head=head,
            detail="database schema is not at the migration head",
        )
    return ReadinessResponse(
        status="ready", database="ok", migration_revision=revision, migration_head=head
    )
