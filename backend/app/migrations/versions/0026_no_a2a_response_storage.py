"""Keep external A2A research content in memory only."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_no_a2a_response"
down_revision = "0025_stock_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Retain a non-reversible digest for audit while deleting guest response text.
    op.execute("""
        UPDATE durable_events
        SET payload = payload - 'response'
        WHERE event_type = 'A2A_GUEST_RESPONSE_RECEIVED' AND payload ? 'response'
    """)
    op.drop_column("a2a_reception_requests", "response")


def downgrade() -> None:
    # Previously deleted guest response bodies cannot be restored.
    op.add_column("a2a_reception_requests", sa.Column(
        "response", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
    ))
