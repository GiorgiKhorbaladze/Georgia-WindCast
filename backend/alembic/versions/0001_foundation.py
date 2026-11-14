"""Foundation schema: instance metadata and worker heartbeat.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-11-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instance_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="instance_metadata_single_row"),
    )
    op.execute("INSERT INTO instance_metadata (id) VALUES (1)")
    op.create_table(
        "worker_heartbeat",
        sa.Column("worker_name", sa.String(64), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeat")
    op.drop_table("instance_metadata")
