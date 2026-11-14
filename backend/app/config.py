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
