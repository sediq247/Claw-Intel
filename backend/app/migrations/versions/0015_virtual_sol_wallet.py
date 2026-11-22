"""Move virtual wallet funding to a SOL-denominated balance."""
from alembic import op
import sqlalchemy as sa

revision = "0015_virtual_sol_wallet"
down_revision = "0014_durable_agent_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("paper_accounts", sa.Column("initial_virtual_sol", sa.Numeric(24, 9), nullable=False, server_default="10000"))
    op.add_column("paper_accounts", sa.Column("virtual_sol_balance", sa.Numeric(24, 9), nullable=False, server_default="10000"))
    # Keep legacy USD columns intact so a downgrade can restore the prior ledger.
    # The application uses only the SOL fields after this migration.


def downgrade():
    op.drop_column("paper_accounts", "virtual_sol_balance")
    op.drop_column("paper_accounts", "initial_virtual_sol")
