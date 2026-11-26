"""Add immutable, versioned market forecasts without source evidence retention."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_market_forecasts"
down_revision = "0018_autonomous_schedule"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "market_forecasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_class", sa.String(24), nullable=False, server_default="crypto"),
        sa.Column("asset_key", sa.String(240), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("forecast", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("market_forecasts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("asset_key", "version", name="uq_market_forecast_asset_version"),
    )
    op.create_index("ix_market_forecast_asset_created", "market_forecasts", ["asset_key", "created_at"])
    op.create_index("ix_market_forecast_investigation", "market_forecasts", ["investigation_id"])


def downgrade():
    op.drop_index("ix_market_forecast_investigation", table_name="market_forecasts")
    op.drop_index("ix_market_forecast_asset_created", table_name="market_forecasts")
    op.drop_table("market_forecasts")
