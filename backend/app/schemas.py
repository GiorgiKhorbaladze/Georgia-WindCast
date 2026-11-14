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
    source: SourceAttribution


class WorkerStatus(BaseModel):
    state: Literal["running", "stale", "never_seen"]
    last_seen_at: datetime | None


class SourceStatus(BaseModel):
    id: str
    state: SourceState
    detail: str | None = None


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
