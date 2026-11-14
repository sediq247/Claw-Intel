"""Track simulated current prices for demo portfolio positions.

Revision ID: 0003_demo_mark_price
Revises: 0002_agent_workflows
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_demo_mark_price"
down_revision = "0002_agent_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("demo_positions", sa.Column("current_price", sa.Numeric(24, 12), nullable=True))
    op.execute("UPDATE demo_positions SET current_price = average_price")


def downgrade():
    op.drop_column("demo_positions", "current_price")
