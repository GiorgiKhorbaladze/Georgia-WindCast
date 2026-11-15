"""ORM models.

All timestamps are stored as ``timestamptz`` and handled in UTC. Display conversion to
Asia/Tbilisi happens only in the UI layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


class GenerationReading(Base):
    """One national-aggregate reading from a source period file.

    ``period_label_at`` is the timestamp the source attaches to the averaging period (UTC).
    ``retrieved_at`` is when this service fetched it. The two are never conflated.
    """

    __tablename__ = "generation_reading"
    __table_args__ = (
        UniqueConstraint("source", "metric", "period_label_at", name="uq_generation_period"),
        CheckConstraint("value_mw = value_mw", name="ck_generation_value_not_nan"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    period_label_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_label_local: Mapped[str] = mapped_column(String(32), nullable=False)
    value_mw: Mapped[float] = mapped_column(Float(precision=53), nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    etag: Mapped[str | None] = mapped_column(String(128))
    source_last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class SourceStatusRecord(Base):
    """Polling state per external source: availability monitoring and backoff."""

    __tablename__ = "source_status"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    backoff_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeatherValue(Base):
    """Model wind at one site, height and valid time, from one product run.

    ``run_ref`` identifies the run: the ISO initialisation time for forecasts, or the product
    name for reanalysis (which is revised in place).
    """

    __tablename__ = "weather_value"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "product",
            "model",
            "run_ref",
            "valid_at",
            "height_m",
            name="uq_weather_value",
        ),
        Index("ix_weather_site_height_valid", "site_id", "height_m", "valid_at"),
        CheckConstraint("speed_ms IS NULL OR speed_ms >= 0", name="ck_weather_speed_nonneg"),
        CheckConstraint(
            "direction_deg IS NULL OR (direction_deg >= 0 AND direction_deg <= 360)",
            name="ck_weather_direction_range",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(String(32), nullable=False)
    product: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(32), nullable=False)
    run_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    height_m: Mapped[int] = mapped_column(Integer, nullable=False)
    speed_ms: Mapped[float | None] = mapped_column(Float(precision=53))
    direction_deg: Mapped[float | None] = mapped_column(Float(precision=53))
    grid_latitude: Mapped[float | None] = mapped_column(Float(precision=53))
    grid_longitude: Mapped[float | None] = mapped_column(Float(precision=53))
    grid_elevation_m: Mapped[float | None] = mapped_column(Float(precision=53))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
