"""Initial worker heartbeat; all timestamps are UTC-aware."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "worker_heartbeat",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("worker_heartbeat")
