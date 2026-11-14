"""ORM models.

All timestamps are stored as ``timestamptz`` and handled in UTC. Display conversion to
Asia/Tbilisi happens only in the UI layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkerHeartbeat(Base):
    """Last-seen record per worker instance; used for liveness reporting."""

    __tablename__ = "worker_heartbeat"

    worker_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)


class InstanceMetadata(Base):
    """Single-row record created by the initial migration.

    It lets operators (and the Compose smoke test) verify that the database volume survives
    restarts: ``installed_at`` must stay unchanged across ``docker compose restart``.
    """

    __tablename__ = "instance_metadata"

    id: Mapped[int] = mapped_column(primary_key=True)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
