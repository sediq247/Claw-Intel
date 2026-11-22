"""Bind private Trading Room investigations to the verified account."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_investigation_owner"
down_revision = "0009_account_chat_owner"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("investigations", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_investigation_user", "investigations", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_investigations_user_id", "investigations", ["user_id"])
    op.execute(sa.text(
        "UPDATE investigations AS i SET user_id = s.user_id "
        "FROM browser_sessions AS s WHERE i.session_id = s.id AND i.department = 'trading' AND s.user_id IS NOT NULL"
    ))


def downgrade():
    op.drop_index("ix_investigations_user_id", table_name="investigations")
    op.drop_constraint("fk_investigation_user", "investigations", type_="foreignkey")
    op.drop_column("investigations", "user_id")
