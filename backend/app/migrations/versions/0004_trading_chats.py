"""Add switchable Trading Room chats and associate prior messages."""
from alembic import op
import sqlalchemy as sa

revision = "0004_trading_chats"
down_revision = "0003_demo_mark_price"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trading_chats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default="New chat"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id"], ["browser_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trading_chat_session_updated", "trading_chats", ["session_id", "updated_at"])
    op.add_column("conversation_messages", sa.Column("chat_id", sa.UUID(), nullable=True))
    op.add_column("investigations", sa.Column("chat_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_message_trading_chat", "conversation_messages", "trading_chats", ["chat_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_investigation_trading_chat", "investigations", "trading_chats", ["chat_id"], ["id"], ondelete="CASCADE")
    op.execute("""
      INSERT INTO trading_chats (id, session_id, title, created_at, updated_at)
      SELECT gen_random_uuid(), session_id, 'Previous chat', min(created_at), max(created_at)
      FROM conversation_messages
      WHERE department='trading' AND session_id IS NOT NULL
      GROUP BY session_id
    """)
    op.execute("""
      UPDATE conversation_messages m SET chat_id=c.id
      FROM trading_chats c
      WHERE m.department='trading' AND m.session_id=c.session_id
    """)
    op.execute("""
      UPDATE investigations i SET chat_id=c.id
      FROM trading_chats c
      WHERE i.department='trading' AND i.session_id=c.session_id
    """)


def downgrade():
    op.drop_constraint("fk_investigation_trading_chat", "investigations", type_="foreignkey")
    op.drop_constraint("fk_message_trading_chat", "conversation_messages", type_="foreignkey")
    op.drop_column("investigations", "chat_id")
    op.drop_column("conversation_messages", "chat_id")
    op.drop_index("ix_trading_chat_session_updated", table_name="trading_chats")
    op.drop_table("trading_chats")
