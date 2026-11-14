"""Initial PostgreSQL application schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("browser_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wallet_connected", sa.Boolean(), nullable=False),
        sa.Column("wallet_address", sa.String(96)), sa.Column("wallet_label", sa.String(80)))
    op.create_table("conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE")),
        sa.Column("department", sa.String(20), nullable=False), sa.Column("agent_id", sa.String(24), nullable=False),
        sa.Column("role", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_message_session_department_created", "conversation_messages", ["session_id", "department", "created_at"])
    op.create_table("evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="SET NULL")),
        sa.Column("department", sa.String(20), nullable=False), sa.Column("chain", sa.String(48), nullable=False),
        sa.Column("token_address", sa.String(160), nullable=False), sa.Column("source", sa.String(128), nullable=False),
        sa.Column("data_kind", sa.String(16), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False), sa.Column("limitations", sa.Text()))
    op.create_table("durable_events",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("department", sa.String(20), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE")),
        sa.Column("event_type", sa.String(40), nullable=False), sa.Column("agent_id", sa.String(24)),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_event_dept_session_sequence", "durable_events", ["department", "session_id", "sequence"])
    op.create_table("demo_wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("near_balance", sa.Numeric(24, 8), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("demo_quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain", sa.String(48), nullable=False), sa.Column("token_address", sa.String(160), nullable=False),
        sa.Column("side", sa.String(8), nullable=False), sa.Column("amount_near", sa.Numeric(24, 8), nullable=False),
        sa.Column("price", sa.Numeric(24, 12), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False))
    op.create_table("demo_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(96), nullable=False), sa.Column("chain", sa.String(48), nullable=False),
        sa.Column("token_address", sa.String(160), nullable=False), sa.Column("side", sa.String(8), nullable=False),
        sa.Column("amount_near", sa.Numeric(24, 8), nullable=False), sa.Column("quote_price", sa.Numeric(24, 12), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_trade_idempotency_per_session"))
    op.create_table("demo_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain", sa.String(48), nullable=False), sa.Column("token_address", sa.String(160), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 12), nullable=False), sa.Column("average_price", sa.Numeric(24, 12), nullable=False),
        sa.UniqueConstraint("session_id", "chain", "token_address", name="uq_position_token_per_session"))


def downgrade():
    op.drop_table("demo_positions")
    op.drop_table("demo_trades")
    op.drop_table("demo_quotes")
    op.drop_table("demo_wallets")
    op.drop_index("ix_event_dept_session_sequence", table_name="durable_events")
    op.drop_table("durable_events")
    op.drop_table("evidence")
    op.drop_index("ix_message_session_department_created", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_table("browser_sessions")
