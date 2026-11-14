"""Open-Meteo model wind values per site, height, valid time and run.

Revision ID: 0003_weather
Revises: 0002_gse_generation
Create Date: 2026-11-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_weather"
down_revision: str | None = "0002_gse_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weather_value",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.String(32), nullable=False),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(32), nullable=False),
        sa.Column("run_ref", sa.String(40), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True)),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("height_m", sa.Integer(), nullable=False),
        sa.Column("speed_ms", sa.Float(precision=53)),
        sa.Column("direction_deg", sa.Float(precision=53)),
        sa.Column("grid_latitude", sa.Float(precision=53)),
        sa.Column("grid_longitude", sa.Float(precision=53)),
        sa.Column("grid_elevation_m", sa.Float(precision=53)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "site_id",
            "product",
            "model",
            "run_ref",
            "valid_at",
            "height_m",
            name="uq_weather_value",
        ),
        sa.CheckConstraint("speed_ms IS NULL OR speed_ms >= 0", name="ck_weather_speed_nonneg"),
        sa.CheckConstraint(
            "direction_deg IS NULL OR (direction_deg >= 0 AND direction_deg <= 360)",
            name="ck_weather_direction_range",
        ),
    )
    op.create_index(
        "ix_weather_site_height_valid", "weather_value", ["site_id", "height_m", "valid_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_weather_site_height_valid", table_name="weather_value")
    op.drop_table("weather_value")
