"""Add wallet-owned watchlists and recurring price alerts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_watchlists_alerts"
down_revision = "0010_investigation_owner"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "watchlist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("token_address", sa.String(128), nullable=False),
        sa.Column("label", sa.String(80), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "chain", "token_address", name="uq_watchlist_user_token"),
    )
    op.create_index("ix_watchlist_user_created", "watchlist_entries", ["user_id", "created_at"])

    op.create_table(
        "price_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("watchlist_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("watchlist_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("token_address", sa.String(128), nullable=False),
        sa.Column("condition", sa.String(8), nullable=False),
        sa.Column("threshold_usd", sa.Numeric(30, 16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_triggered", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_observed_price_usd", sa.Numeric(30, 16)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("condition IN ('above', 'below')", name="ck_price_alert_condition"),
        sa.CheckConstraint("threshold_usd > 0", name="ck_price_alert_threshold_positive"),
    )
    op.create_index("ix_price_alerts_user_enabled", "price_alerts", ["user_id", "enabled"])

    op.create_table(
        "price_alert_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("price_alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_price_usd", sa.Numeric(30, 16), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_price_alert_events_user_created", "price_alert_events", ["user_id", "created_at"])


def downgrade():
    op.drop_index("ix_price_alert_events_user_created", table_name="price_alert_events")
    op.drop_table("price_alert_events")
    op.drop_index("ix_price_alerts_user_enabled", table_name="price_alerts")
    op.drop_table("price_alerts")
    op.drop_index("ix_watchlist_user_created", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
