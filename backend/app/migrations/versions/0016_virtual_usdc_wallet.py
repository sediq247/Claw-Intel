"""Add a USD-pegged virtual balance for wallet-style paper trading."""
from alembic import op
import sqlalchemy as sa

revision = "0016_virtual_usdc_wallet"
down_revision = "0015_virtual_sol_wallet"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("paper_accounts", sa.Column("initial_virtual_usdc", sa.Numeric(24, 6), nullable=False, server_default="10000"))
    op.add_column("paper_accounts", sa.Column("virtual_usdc_balance", sa.Numeric(24, 6), nullable=False, server_default="10000"))


def downgrade():
    op.drop_column("paper_accounts", "virtual_usdc_balance")
    op.drop_column("paper_accounts", "initial_virtual_usdc")
