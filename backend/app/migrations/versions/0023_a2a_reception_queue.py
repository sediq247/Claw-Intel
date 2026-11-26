"""Persist bounded, attributed War Room guest reception requests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_a2a_reception_queue"
down_revision = "0022_hourly_market_phases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "a2a_reception_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requester_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("configured_url", sa.String(length=600), nullable=False),
        sa.Column("endpoint", sa.String(length=600), nullable=False),
        sa.Column("guest_name", sa.String(length=120), nullable=False),
        sa.Column("guest_description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("trust_state", sa.String(length=40), server_default="operator_allowlisted_unverified", nullable=False),
        sa.Column("screening", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("rejection_reason", sa.String(length=200), nullable=True),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued','admitted','completed','failed','dismissed','rejected','expired')",
                           name="ck_a2a_reception_status"),
        sa.ForeignKeyConstraint(["requester_session_id"], ["browser_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_started_at", "configured_url", name="uq_a2a_guest_per_session"),
    )
    op.create_index("ix_a2a_reception_session_status_queued", "a2a_reception_requests",
                    ["session_started_at", "status", "queued_at"])


def downgrade() -> None:
    op.drop_index("ix_a2a_reception_session_status_queued", table_name="a2a_reception_requests")
    op.drop_table("a2a_reception_requests")
