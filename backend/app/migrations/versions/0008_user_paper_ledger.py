"""Add isolated USD paper accounts, positions and idempotent orders."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_user_paper_ledger"
down_revision = "0007_wallet_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paper_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("initial_cash_usd", sa.Numeric(20, 2), nullable=False, server_default="10000"),
        sa.Column("cash_usd", sa.Numeric(20, 8), nullable=False, server_default="10000"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("token_address", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(48), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 16), nullable=False),
        sa.Column("average_price_usd", sa.Numeric(30, 16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "chain", "token_address", name="uq_paper_position_token"),
    )
    op.create_index("ix_paper_positions_account_id", "paper_positions", ["account_id"])
    op.create_table(
        "paper_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(96), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("token_address", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(48), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("amount_usd", sa.Numeric(20, 8), nullable=False),
        sa.Column("price_usd", sa.Numeric(30, 16), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 16), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_paper_order_idempotency"),
    )
    op.create_index("ix_paper_orders_account_id", "paper_orders", ["account_id"])


def downgrade():
    op.drop_index("ix_paper_orders_account_id", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_positions_account_id", table_name="paper_positions")
    op.drop_table("paper_positions")
    op.drop_table("paper_accounts")
