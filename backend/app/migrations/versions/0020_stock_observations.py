"""Store normalized daily adjusted stock bars from an explicit provider."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_stock_observations"
down_revision = "0019_market_forecasts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("market_date", sa.Date(), nullable=False),
        sa.Column("open_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("high_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("low_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("close_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.Numeric(30, 0), nullable=False),
        sa.Column("source", sa.String(80), nullable=False, server_default="Alpha Vantage Daily Adjusted"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "market_date", name="uq_stock_observation_symbol_date"),
    )


def downgrade():
    op.drop_table("stock_observations")
