"""Add verified wallet identities and single-use wallet challenges."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_wallet_identity"
down_revision = "0006_chat_scoped_agent_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "wallet_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("address", sa.String(128), nullable=False),
        sa.Column("wallet_name", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain", "address", name="uq_wallet_identity_chain_address"),
    )
    op.create_index("ix_wallet_identity_user", "wallet_identities", ["user_id"])
    op.create_table(
        "wallet_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("address", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("nonce_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_wallet_challenge_session_expiry", "wallet_challenges", ["session_id", "expires_at"])
    op.add_column("browser_sessions", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_browser_session_user", "browser_sessions", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_browser_sessions_user_id", "browser_sessions", ["user_id"])


def downgrade():
    op.drop_index("ix_browser_sessions_user_id", table_name="browser_sessions")
    op.drop_constraint("fk_browser_session_user", "browser_sessions", type_="foreignkey")
    op.drop_column("browser_sessions", "user_id")
    op.drop_index("ix_wallet_challenge_session_expiry", table_name="wallet_challenges")
    op.drop_table("wallet_challenges")
    op.drop_index("ix_wallet_identity_user", table_name="wallet_identities")
    op.drop_table("wallet_identities")
    op.drop_table("users")
