"""GSE national wind generation readings and source polling status.

Revision ID: 0002_gse_generation
Revises: 0001_foundation
Create Date: 2026-11-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_gse_generation"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_reading",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("period_label_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_label_local", sa.String(32), nullable=False),
        sa.Column("value_mw", sa.Float(precision=53), nullable=False),
        sa.Column("quality", sa.String(16), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("etag", sa.String(128)),
        sa.Column("source_last_modified", sa.DateTime(timezone=True)),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("source", "metric", "period_label_at", name="uq_generation_period"),
        sa.CheckConstraint("value_mw = value_mw", name="ck_generation_value_not_nan"),
    )
    op.create_table(
        "source_status",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_http_status", sa.Integer()),
        sa.Column("backoff_until", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("source_status")
    op.drop_table("generation_reading")
