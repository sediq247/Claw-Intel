from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    wallet_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(String(96))
    wallet_label: Mapped[str | None] = mapped_column(String(80))


class TradingChat(Base):
    __tablename__ = "trading_chats"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="New chat", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    __table_args__ = (Index("ix_trading_chat_session_updated", "session_id", "updated_at"),)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"))
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(24), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chat_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trading_chats.id", ondelete="CASCADE"))
    investigation_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (Index("ix_message_session_department_created", "session_id", "department", "created_at"),)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="SET NULL"))
    investigation_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"))
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    chain: Mapped[str] = mapped_column(String(48), nullable=False)
    token_address: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    data_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    fields: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    limitations: Mapped[str | None] = mapped_column(Text)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"))
    chat_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trading_chats.id", ondelete="CASCADE"))
    chain: Mapped[str] = mapped_column(String(48), nullable=False)
    token_address: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(String(48))
    confidence: Mapped[object | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_investigation_dept_session_updated", "department", "session_id", "updated_at"),)


class InvestigationFinding(Base):
    __tablename__ = "investigation_findings"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    investigation_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False)
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"))
    agent_id: Mapped[str] = mapped_column(String(24), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[object | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (Index("ix_finding_investigation_round", "investigation_id", "round_number"),)


class DebateRound(Base):
    __tablename__ = "debate_rounds"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    investigation_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    challenge_agent: Mapped[str | None] = mapped_column(String(24))
    notes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("investigation_id", "round_number", name="uq_debate_round_number"),)


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"))
    agent_id: Mapped[str] = mapped_column(String(24), nullable=False)
    investigation_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (Index("ix_memory_dept_session_agent_created", "department", "session_id", "agent_id", "created_at"),)


class LLMUsage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"))
    investigation_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"))
    agent_id: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[object | None] = mapped_column(Numeric(16, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (Index("ix_llm_usage_dept_created", "department", "created_at"),)


class DurableEvent(Base):
    __tablename__ = "durable_events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[object] = mapped_column(UUID(as_uuid=True), unique=True, default=uuid4, nullable=False)
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (Index("ix_event_dept_session_sequence", "department", "session_id", "sequence"),)


class DemoWallet(Base):
    __tablename__ = "demo_wallets"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), unique=True, nullable=False)
    near_balance: Mapped[object] = mapped_column(Numeric(24, 8), default=1000, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Trade(Base):
    __tablename__ = "demo_trades"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    chain: Mapped[str] = mapped_column(String(48), nullable=False)
    token_address: Mapped[str] = mapped_column(String(160), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_near: Mapped[object] = mapped_column(Numeric(24, 8), nullable=False)
    quote_price: Mapped[object] = mapped_column(Numeric(24, 12), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("session_id", "idempotency_key", name="uq_trade_idempotency_per_session"),)


class DemoQuote(Base):
    __tablename__ = "demo_quotes"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[str] = mapped_column(String(48), nullable=False)
    token_address: Mapped[str] = mapped_column(String(160), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_near: Mapped[object] = mapped_column(Numeric(24, 8), nullable=False)
    price: Mapped[object] = mapped_column(Numeric(24, 12), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Position(Base):
    __tablename__ = "demo_positions"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[str] = mapped_column(String(48), nullable=False)
    token_address: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[object] = mapped_column(Numeric(36, 12), nullable=False)
    average_price: Mapped[object] = mapped_column(Numeric(24, 12), nullable=False)
    current_price: Mapped[object | None] = mapped_column(Numeric(24, 12))
    __table_args__ = (UniqueConstraint("session_id", "chain", "token_address", name="uq_position_token_per_session"),)
