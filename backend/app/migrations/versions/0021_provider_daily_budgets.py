"""Add a shared daily provider-call budget for quota-limited data feeds."""
from alembic import op
import sqlalchemy as sa


revision = "0021_provider_daily_budgets"
down_revision = "0020_stock_observations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_daily_budgets",
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("budget_date", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("provider", "budget_date", name="pk_provider_daily_budgets"),
        sa.CheckConstraint("request_count >= 0", name="ck_provider_daily_budget_nonnegative"),
    )


def downgrade():
    op.drop_table("provider_daily_budgets")
