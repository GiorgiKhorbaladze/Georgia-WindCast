"""Runtime configuration, read exclusively from environment variables.

No credentials are stored in tracked files; see ``.env.example`` at the repository root.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WINDCAST_", extra="ignore")

    app_env: AppEnv = AppEnv.DEVELOPMENT
    database_url: str = Field(
        default="postgresql+psycopg://windcast:windcast@localhost:5432/windcast",
        description="SQLAlchemy URL. Override via WINDCAST_DATABASE_URL.",
    )
    # Fixture data exists only for automated tests. It must never be served in production.
    allow_fixtures: bool = False
    worker_heartbeat_seconds: int = Field(default=30, ge=1, le=3600)
    # The worker is considered unhealthy if no heartbeat was recorded within this window.
    worker_stale_after_seconds: int = Field(default=120, ge=1)
    cors_origins: list[str] = Field(default_factory=list)

    # GSE national wind aggregate (issue #3). Disabled by default until the owner confirms
    # reuse terms; see docs/sources/gse.md.
    gse_ingestion_enabled: bool = False
    gse_base_url: str = "https://admin.gse.com.ge/storage/uploads/fact/"
    gse_poll_seconds: int = Field(default=60, ge=30, le=3600)
    # GSE publishes a period file roughly 77 s after its label; do not ask earlier than this.
    gse_publication_lag_seconds: int = Field(default=75, ge=0, le=1800)
    gse_catchup_periods: int = Field(default=20, ge=1, le=480)
    gse_max_requests_per_tick: int = Field(default=4, ge=1, le=20)
    gse_missing_attempts: int = Field(default=3, ge=1, le=20)
    gse_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    # A reading older than this (by its source label) is reported as stale.
    gse_fresh_within_seconds: int = Field(default=600, ge=60)
    # Optional identifying User-Agent for requests to GSE. Unset: the HTTP library default.
    gse_user_agent: str | None = None

    @model_validator(mode="after")
    def _forbid_fixtures_in_production(self) -> Settings:
        if self.app_env is AppEnv.PRODUCTION and self.allow_fixtures:
            raise ValueError(
                "WINDCAST_ALLOW_FIXTURES must be false when WINDCAST_APP_ENV=production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
