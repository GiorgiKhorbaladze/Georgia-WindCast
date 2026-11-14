"""Public API contracts.

The generation contract is deliberately limited to the *national aggregate* published by GSE.
There is no per-site MW field anywhere in this API, by design.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    # A reading exists but the source supplied no trustworthy observation timestamp.
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"


class SourceState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "error"]
    migration_revision: str | None
    migration_head: str | None
    detail: str | None = None


class SourceAttribution(BaseModel):
    name: str
    url: str


class GenerationLatest(BaseModel):
    scope: Literal["national_aggregate"] = "national_aggregate"
    unit: Literal["MW"] = "MW"
    freshness: Freshness
    value_mw: float | None = Field(
        default=None, description="Actual national wind generation reported by GSE."
    )
    source_observed_at: datetime | None = Field(
        default=None, description="Observation time supplied by the source, UTC."
    )
    retrieved_at: datetime | None = Field(
        default=None, description="Time this service last fetched the reading, UTC."
    )
    reason: str | None = Field(default=None, description="Why the value is not fresh.")
    quality: str | None = Field(
        default=None, description="Raw source quality code, e.g. ACT. Meanings unconfirmed."
    )
    quality_flagged: bool = Field(
        default=False, description="True when the source quality code is not ACT."
    )
    period_seconds: int | None = Field(
        default=None, description="Length of the averaging period behind the value."
    )
    source: SourceAttribution


class GenerationPoint(BaseModel):
    t: datetime = Field(description="Source period label, UTC.")
    value_mw: float
    quality: str


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class GenerationHistory(BaseModel):
    scope: Literal["national_aggregate"] = "national_aggregate"
    unit: Literal["MW"] = "MW"
    start: datetime
    end: datetime
    cadence_seconds: int
    collection_started_at: datetime | None = Field(
        description="Earliest reading ever stored. Nothing before this was collected."
    )
    points: list[GenerationPoint]
    gaps: list[TimeRange] = Field(
        description="Intervals inside the range with no reading. Never interpolated."
    )
    source: SourceAttribution


class WorkerStatus(BaseModel):
    state: Literal["running", "stale", "never_seen"]
    last_seen_at: datetime | None


class SourceStatus(BaseModel):
    id: str
    state: SourceState
    detail: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    backoff_until: datetime | None = None


class SiteSummary(BaseModel):
    id: str
    name_ka: str
    name_en: str
    coordinates_verified: bool
    latitude: float | None = None
    longitude: float | None = None


class SystemStatus(BaseModel):
    generated_at: datetime
    app_env: str
    worker: WorkerStatus
    sources: list[SourceStatus]
    sites: list[SiteSummary]
