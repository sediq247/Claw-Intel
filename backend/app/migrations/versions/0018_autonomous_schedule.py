"""Persist the autonomous War Room's work and rest cadence."""
from alembic import op
import sqlalchemy as sa

revision = "0018_autonomous_schedule"
down_revision = "0017_virtual_usdc_transfers"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_evidence_dept_kind_chain_address", "evidence",
                    ["department", "data_kind", "chain", "token_address"])
    op.create_table(
        "autonomous_schedule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phase", sa.String(12), nullable=False),
        sa.Column("phase_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phase_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_ambient_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_news_url", sa.String(1000)),
        sa.Column("rugged_tokens_7d", sa.Integer()),
        sa.Column("rugcheck_updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_autonomous_schedule_singleton"),
        sa.CheckConstraint("phase IN ('working','draining','resting')", name="ck_autonomous_schedule_phase"),
    )


def downgrade():
    op.drop_table("autonomous_schedule")
    op.drop_index("ix_evidence_dept_kind_chain_address", table_name="evidence")
