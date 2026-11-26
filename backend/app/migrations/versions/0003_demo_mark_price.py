"""Legacy demo-position migration retained for databases at older revisions.

Revision ID: 0003_demo_mark_price
Revises: 0002_agent_workflows
"""
from alembic import op

revision = "0003_demo_mark_price"
down_revision = "0002_agent_workflows"
branch_labels = None
depends_on = None


def upgrade():
    # Demo positions were removed from clean-install schemas. Existing databases
    # retain the legacy table only until the one-time cleanup migration 0027.
    pass


def downgrade():
    pass
