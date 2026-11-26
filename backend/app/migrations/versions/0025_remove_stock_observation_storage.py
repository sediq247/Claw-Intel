"""Keep daily stock bars in process memory instead of PostgreSQL."""
from alembic import op
import sqlalchemy as sa


revision = "0025_stock_cache"
down_revision = "0024_remove_persisted_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # OHLCV is source data, not an analysis result; remove all previously cached bars.
    op.drop_table("stock_observations")


def downgrade() -> None:
    # A downgrade recreates an empty cache; deleted provider bars cannot be restored.
    from sqlalchemy.dialects import postgresql
    op.create_table(
        "stock_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("market_date", sa.Date(), nullable=False),
        sa.Column("open_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("high_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("low_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("close_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.Numeric(30, 0), nullable=False),
        sa.Column("source", sa.String(length=80), server_default="Alpha Vantage Daily Adjusted", nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "market_date", name="uq_stock_observation_symbol_date"),
    )
