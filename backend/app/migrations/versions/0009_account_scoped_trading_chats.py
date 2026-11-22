"""Scope private Trading Room chats to the verified wallet account."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_account_chat_owner"
down_revision = "0008_user_paper_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("trading_chats", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_trading_chat_user", "trading_chats", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_trading_chats_user_id", "trading_chats", ["user_id"])
    op.execute(sa.text(
        "UPDATE trading_chats AS c SET user_id = s.user_id "
        "FROM browser_sessions AS s WHERE c.session_id = s.id AND s.user_id IS NOT NULL"
    ))


def downgrade():
    op.drop_index("ix_trading_chats_user_id", table_name="trading_chats")
    op.drop_constraint("fk_trading_chat_user", "trading_chats", type_="foreignkey")
    op.drop_column("trading_chats", "user_id")
