"""Add durable investigations, debate, per-agent memory, and LLM usage.

Revision ID: 0002_agent_workflows
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_agent_workflows"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "investigations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("department", sa.String(20), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE")),
        sa.Column("chain", sa.String(48), nullable=False),
        sa.Column("token_address", sa.String(160), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scenario_id", sa.String(48)),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_investigation_dept_session_updated", "investigations", ["department", "session_id", "updated_at"])

    op.create_table(
        "investigation_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department", sa.String(20), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE")),
        sa.Column("agent_id", sa.String(24), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_finding_investigation_round", "investigation_findings", ["investigation_id", "round_number"])

    op.create_table(
        "debate_rounds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("challenge_agent", sa.String(24)),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("investigation_id", "round_number", name="uq_debate_round_number"),
    )

    op.create_table(
        "agent_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("department", sa.String(20), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE")),
        sa.Column("agent_id", sa.String(24), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="SET NULL")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_dept_session_agent_created", "agent_memories", ["department", "session_id", "agent_id", "created_at"])

    op.create_table(
        "llm_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("department", sa.String(20), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("browser_sessions.id", ondelete="CASCADE")),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="SET NULL")),
        sa.Column("agent_id", sa.String(24), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("cost_usd", sa.Numeric(16, 8)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_usage_dept_created", "llm_usage", ["department", "created_at"])

    op.add_column("conversation_messages", sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_message_investigation", "conversation_messages", "investigations", ["investigation_id"], ["id"], ondelete="SET NULL")
    op.add_column("conversation_messages", sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("conversation_messages", "simulated", server_default=None)

    op.add_column("evidence", sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_evidence_investigation", "evidence", "investigations", ["investigation_id"], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("fk_evidence_investigation", "evidence", type_="foreignkey")
    op.drop_column("evidence", "investigation_id")
    op.drop_constraint("fk_message_investigation", "conversation_messages", type_="foreignkey")
    op.drop_column("conversation_messages", "simulated")
    op.drop_column("conversation_messages", "investigation_id")
    op.drop_index("ix_llm_usage_dept_created", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_memory_dept_session_agent_created", table_name="agent_memories")
    op.drop_table("agent_memories")
    op.drop_table("debate_rounds")
    op.drop_index("ix_finding_investigation_round", table_name="investigation_findings")
    op.drop_table("investigation_findings")
    op.drop_index("ix_investigation_dept_session_updated", table_name="investigations")
    op.drop_table("investigations")
