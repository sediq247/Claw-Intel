"""Scope Trading Room agent memory to its owning chat."""
from alembic import op
import sqlalchemy as sa


revision = "0006_chat_scoped_agent_memory"
down_revision = "0005_chat_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_memories", sa.Column("chat_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_agent_memory_trading_chat", "agent_memories", "trading_chats",
        ["chat_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_agent_memory_chat_agent_created", "agent_memories", ["chat_id", "agent_id", "created_at"])


def downgrade():
    op.drop_index("ix_agent_memory_chat_agent_created", table_name="agent_memories")
    op.drop_constraint("fk_agent_memory_trading_chat", "agent_memories", type_="foreignkey")
    op.drop_column("agent_memories", "chat_id")
