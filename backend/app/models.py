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
    user_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class WalletIdentity(Base):
    __tablename__ = "wallet_identities"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    wallet_name: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (UniqueConstraint("chain", "address", name="uq_wallet_identity_chain_address"), Index("ix_wallet_identity_user", "user_id"))


class WalletChallenge(Base):
    __tablename__ = "wallet_challenges"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (Index("ix_wallet_challenge_session_expiry", "session_id", "expires_at"),)


class TradingChat(Base):
    __tablename__ = "trading_chats"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    attachments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
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
    __table_args__ = (Index("ix_evidence_dept_kind_chain_address", "department", "data_kind", "chain", "token_address"),)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    department: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"))
    user_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    chat_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trading_chats.id", ondelete="CASCADE"))
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


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    initial_cash_usd: Mapped[object] = mapped_column(Numeric(20, 2), default=10000, nullable=False)
    cash_usd: Mapped[object] = mapped_column(Numeric(20, 8), default=10000, nullable=False)
    initial_virtual_sol: Mapped[object] = mapped_column(Numeric(24, 9), default=10000, nullable=False)
    virtual_sol_balance: Mapped[object] = mapped_column(Numeric(24, 9), default=10000, nullable=False)
    initial_virtual_usdc: Mapped[object] = mapped_column(Numeric(24, 6), default=10000, nullable=False)
    virtual_usdc_balance: Mapped[object] = mapped_column(Numeric(24, 6), default=10000, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(48), nullable=False)
    quantity: Mapped[object] = mapped_column(Numeric(36, 16), nullable=False)
    average_price_usd: Mapped[object] = mapped_column(Numeric(30, 16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    __table_args__ = (UniqueConstraint("account_id", "chain", "token_address", name="uq_paper_position_token"),)


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(48), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_usd: Mapped[object] = mapped_column(Numeric(20, 8), nullable=False)
    price_usd: Mapped[object] = mapped_column(Numeric(30, 16), nullable=False)
    quantity: Mapped[object] = mapped_column(Numeric(36, 16), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (UniqueConstraint("account_id", "idempotency_key", name="uq_paper_order_idempotency"),)


class PaperTransfer(Base):
    __tablename__ = "paper_transfers"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    sender_account_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False)
    recipient_account_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False)
    amount_usdc: Mapped[object] = mapped_column(Numeric(24, 6), nullable=False)
    recipient_chain: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_address: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        UniqueConstraint("sender_account_id", "idempotency_key", name="uq_paper_transfer_idempotency"),
        Index("ix_paper_transfer_sender_created", "sender_account_id", "created_at"),
        Index("ix_paper_transfer_recipient_created", "recipient_account_id", "created_at"),
    )


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "chain", "token_address", name="uq_watchlist_user_token"),
        Index("ix_watchlist_user_created", "user_id", "created_at"),
    )


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    watchlist_entry_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("watchlist_entries.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    condition: Mapped[str] = mapped_column(String(8), nullable=False)
    threshold_usd: Mapped[object] = mapped_column(Numeric(30, 16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_observed_price_usd: Mapped[object | None] = mapped_column(Numeric(30, 16))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (Index("ix_price_alerts_user_enabled", "user_id", "enabled"),)


class PriceAlertEvent(Base):
    __tablename__ = "price_alert_events"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    alert_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("price_alerts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    observed_price_usd: Mapped[object] = mapped_column(Numeric(30, 16), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (Index("ix_price_alert_events_user_created", "user_id", "created_at"),)


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    chat_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class TelegramLinkChallenge(Base):
    __tablename__ = "telegram_link_challenges"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (Index("ix_telegram_challenge_user_created", "user_id", "created_at"),)


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(String(4096), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    __table_args__ = (Index("ix_telegram_outbox_status_available", "status", "available_at"),)


class AgentJob(Base):
    __tablename__ = "agent_jobs"
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_agent_jobs_status_available", "status", "available_at"),
        Index("ix_agent_jobs_status_locked", "status", "locked_at"),
    )


class AutonomousSchedule(Base):
    __tablename__ = "autonomous_schedule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phase: Mapped[str] = mapped_column(String(12), nullable=False, default="working")
    phase_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    phase_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_scan_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_ambient_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_news_url: Mapped[str | None] = mapped_column(String(1000))
    rugged_tokens_7d: Mapped[int | None] = mapped_column(Integer)
    rugcheck_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)
