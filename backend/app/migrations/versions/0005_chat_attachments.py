"""Store bounded text attachments on Trading Room messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_chat_attachments"
down_revision = "0004_trading_chats"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_messages",
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
    )
    op.alter_column("conversation_messages", "attachments", server_default=None)


def downgrade():
    op.drop_column("conversation_messages", "attachments")
