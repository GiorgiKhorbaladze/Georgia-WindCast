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
    # A timely reading whose source quality (or timestamp) is not verified, e.g. GSE quality
    # code other than ACT. The value stays visible but must never be shown as plainly "fresh".
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
    fresh_until: datetime | None = Field(
        default=None,
        description="After this UTC time the reading is stale, even if nothing refreshes it.",
    )
    checked_at: datetime | None = Field(default=None, description="Server time of this answer.")
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
    municipality_en: str | None = None
    municipality_ka: str | None = None
    status_en: str | None = None
    status_ka: str | None = None
    coordinate_source: str | None = None
    coordinate_uncertainty_km: float | None = None
    coordinate_note: str | None = None


class WeatherProduct(StrEnum):
    # Model forecast; past valid times come from earlier runs of the same model.
    FORECAST = "forecast"
    # Retrospective reanalysis (ERA5). A historical model product, not a measurement.
    REANALYSIS = "reanalysis"


class WeatherPoint(BaseModel):
    t: datetime = Field(description="Valid time, UTC.")
    speed_ms: float | None
    direction_deg: float | None = Field(
        description="Meteorological convention: direction the wind blows FROM, degrees."
    )
    run_at: datetime | None = Field(
        default=None, description="Model run that produced this value (forecast products)."
    )


class WeatherSeries(BaseModel):
    product: WeatherProduct
    provider: str
    model: str
    model_label: str
    height_m: int
    run_at: datetime | None = Field(description="Model run (initialisation) time, if published.")
    retrieved_at: datetime | None
    grid_latitude: float | None
    grid_longitude: float | None
    grid_elevation_m: float | None
    supported: bool = Field(description="False when this product does not offer this height.")
    provenance: Literal["single_run", "mixed_runs", "reanalysis", "none"] = Field(
        default="none",
        description=(
            "single_run: every point is from run_at. mixed_runs: points come from several runs; "
            "see each point's run_at (series run_at is then null)."
        ),
    )
    points: list[WeatherPoint]


class SiteWeather(BaseModel):
    site: SiteSummary
    height_m: int
    unit: Literal["m/s"] = "m/s"
    measured: Literal[False] = False
    history: WeatherSeries = Field(
        description="Past valid times: latest available forecast-run value for each hour."
    )
    forecast: WeatherSeries = Field(description="Latest model run, future valid times.")
    reanalysis: WeatherSeries
    attribution: list[SourceAttribution]


class WeatherNow(BaseModel):
    site_id: str
    height_m: int
    valid_at: datetime | None
    speed_ms: float | None
    direction_deg: float | None
    model: str | None
    run_at: datetime | None
    measured: Literal[False] = False


class WeatherOverview(BaseModel):
    generated_at: datetime
    unit: Literal["m/s"] = "m/s"
    heights: dict[str, list[int]] = Field(description="Supported heights per product.")
    unsupported_heights: list[int]
    forecast_model: str
    forecast_model_label: str
    forecast_state: Freshness = Field(
        description=(
            "fresh only with a recent run AND enough forward coverage; stale for an old run or "
            "partial coverage; unavailable without a run or once its coverage has expired."
        )
    )
    forecast_reason: str | None = Field(
        default=None,
        description="no_forecast | forecast_expired | partial_coverage | run_outdated",
    )
    forecast_forward_hours: float = Field(
        default=0.0, description="Hours of forecast still ahead of now (never negative)."
    )
    forecast_run_at: datetime | None
    forecast_retrieved_at: datetime | None
    forecast_horizon_end: datetime | None
    sites: list[SiteSummary]
    now: list[WeatherNow]
    attribution: list[SourceAttribution]


class SystemStatus(BaseModel):
    generated_at: datetime
    app_env: str
    worker: WorkerStatus
    sources: list[SourceStatus]
    sites: list[SiteSummary]
