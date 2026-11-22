"""Persist and lease autonomous agent investigations across app restarts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_durable_agent_jobs"
down_revision = "0013_distributed_rate_limits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(40), nullable=False),
        sa.Column("dedupe_key", sa.String(128), unique=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_agent_jobs_attempt_counts"),
        sa.CheckConstraint("status IN ('queued','processing','retrying','completed','dead')", name="ck_agent_jobs_status"),
    )
    op.create_index("ix_agent_jobs_status_available", "agent_jobs", ["status", "available_at"])
    op.create_index("ix_agent_jobs_status_locked", "agent_jobs", ["status", "locked_at"])


def downgrade():
    op.drop_index("ix_agent_jobs_status_locked", table_name="agent_jobs")
    op.drop_index("ix_agent_jobs_status_available", table_name="agent_jobs")
    op.drop_table("agent_jobs")
