"""Support internal transfers between verified Zecto paper wallets."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017_virtual_usdc_transfers"
down_revision = "0016_virtual_usdc_wallet"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paper_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(96), nullable=False),
        sa.Column("sender_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_usdc", sa.Numeric(24, 6), nullable=False),
        sa.Column("recipient_chain", sa.String(16), nullable=False),
        sa.Column("recipient_address", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("sender_account_id", "idempotency_key", name="uq_paper_transfer_idempotency"),
        sa.CheckConstraint("amount_usdc > 0", name="ck_paper_transfer_positive_amount"),
        sa.CheckConstraint("sender_account_id <> recipient_account_id", name="ck_paper_transfer_distinct_accounts"),
    )
    op.create_index("ix_paper_transfer_sender_created", "paper_transfers", ["sender_account_id", "created_at"])
    op.create_index("ix_paper_transfer_recipient_created", "paper_transfers", ["recipient_account_id", "created_at"])


def downgrade():
    op.drop_index("ix_paper_transfer_recipient_created", table_name="paper_transfers")
    op.drop_index("ix_paper_transfer_sender_created", table_name="paper_transfers")
    op.drop_table("paper_transfers")
