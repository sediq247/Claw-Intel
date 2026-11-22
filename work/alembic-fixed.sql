BEGIN;

INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Generating static SQL
INFO  [alembic.runtime.migration] Generating static SQL
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial, Initial PostgreSQL application schema.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial, Initial PostgreSQL application schema.
-- Running upgrade  -> 0001_initial

CREATE TABLE browser_sessions (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    wallet_connected BOOLEAN NOT NULL, 
    wallet_address VARCHAR(96), 
    wallet_label VARCHAR(80), 
    PRIMARY KEY (id)
);

CREATE TABLE conversation_messages (
    id UUID NOT NULL, 
    session_id UUID, 
    department VARCHAR(20) NOT NULL, 
    agent_id VARCHAR(24) NOT NULL, 
    role VARCHAR(16) NOT NULL, 
    content TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE INDEX ix_message_session_department_created ON conversation_messages (session_id, department, created_at);

CREATE TABLE evidence (
    id UUID NOT NULL, 
    session_id UUID, 
    department VARCHAR(20) NOT NULL, 
    chain VARCHAR(48) NOT NULL, 
    token_address VARCHAR(160) NOT NULL, 
    source VARCHAR(128) NOT NULL, 
    data_kind VARCHAR(16) NOT NULL, 
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    fields JSONB NOT NULL, 
    limitations TEXT, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE SET NULL
);

CREATE TABLE durable_events (
    sequence SERIAL NOT NULL, 
    event_id UUID NOT NULL, 
    department VARCHAR(20) NOT NULL, 
    session_id UUID, 
    event_type VARCHAR(40) NOT NULL, 
    agent_id VARCHAR(24), 
    payload JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (sequence), 
    UNIQUE (event_id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE INDEX ix_event_dept_session_sequence ON durable_events (department, session_id, sequence);

CREATE TABLE demo_wallets (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    near_balance NUMERIC(24, 8) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (session_id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE TABLE demo_quotes (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    chain VARCHAR(48) NOT NULL, 
    token_address VARCHAR(160) NOT NULL, 
    side VARCHAR(8) NOT NULL, 
    amount_near NUMERIC(24, 8) NOT NULL, 
    price NUMERIC(24, 12) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    consumed BOOLEAN NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE TABLE demo_trades (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    idempotency_key VARCHAR(96) NOT NULL, 
    chain VARCHAR(48) NOT NULL, 
    token_address VARCHAR(160) NOT NULL, 
    side VARCHAR(8) NOT NULL, 
    amount_near NUMERIC(24, 8) NOT NULL, 
    quote_price NUMERIC(24, 12) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_trade_idempotency_per_session UNIQUE (session_id, idempotency_key), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE TABLE demo_positions (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    chain VARCHAR(48) NOT NULL, 
    token_address VARCHAR(160) NOT NULL, 
    quantity NUMERIC(36, 12) NOT NULL, 
    average_price NUMERIC(24, 12) NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_position_token_per_session UNIQUE (session_id, chain, token_address), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

INSERT INTO alembic_version (version_num) VALUES ('0001_initial') RETURNING alembic_version.version_num;

INFO  [alembic.runtime.migration] Running upgrade 0001_initial -> 0002_agent_workflows, Add durable investigations, debate, per-agent memory, and LLM usage.
INFO  [alembic.runtime.migration] Running upgrade 0001_initial -> 0002_agent_workflows, Add durable investigations, debate, per-agent memory, and LLM usage.
-- Running upgrade 0001_initial -> 0002_agent_workflows

CREATE TABLE investigations (
    id UUID NOT NULL, 
    department VARCHAR(20) NOT NULL, 
    session_id UUID, 
    chain VARCHAR(48) NOT NULL, 
    token_address VARCHAR(160) NOT NULL, 
    title VARCHAR(200) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    scenario_id VARCHAR(48), 
    confidence NUMERIC(5, 2), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE INDEX ix_investigation_dept_session_updated ON investigations (department, session_id, updated_at);

CREATE TABLE investigation_findings (
    id UUID NOT NULL, 
    investigation_id UUID NOT NULL, 
    department VARCHAR(20) NOT NULL, 
    session_id UUID, 
    agent_id VARCHAR(24) NOT NULL, 
    round_number INTEGER NOT NULL, 
    phase VARCHAR(24) NOT NULL, 
    content TEXT NOT NULL, 
    evidence_ids JSONB DEFAULT '[]'::jsonb NOT NULL, 
    confidence NUMERIC(5, 2), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE CASCADE, 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE INDEX ix_finding_investigation_round ON investigation_findings (investigation_id, round_number);

CREATE TABLE debate_rounds (
    id UUID NOT NULL, 
    investigation_id UUID NOT NULL, 
    round_number INTEGER NOT NULL, 
    phase VARCHAR(32) NOT NULL, 
    challenge_agent VARCHAR(24), 
    notes JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_debate_round_number UNIQUE (investigation_id, round_number), 
    FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE CASCADE
);

CREATE TABLE agent_memories (
    id UUID NOT NULL, 
    department VARCHAR(20) NOT NULL, 
    session_id UUID, 
    agent_id VARCHAR(24) NOT NULL, 
    investigation_id UUID, 
    content TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE, 
    FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE SET NULL
);

CREATE INDEX ix_memory_dept_session_agent_created ON agent_memories (department, session_id, agent_id, created_at);

CREATE TABLE llm_usage (
    id UUID NOT NULL, 
    department VARCHAR(20) NOT NULL, 
    session_id UUID, 
    investigation_id UUID, 
    agent_id VARCHAR(24) NOT NULL, 
    provider VARCHAR(32) NOT NULL, 
    model VARCHAR(160) NOT NULL, 
    input_tokens INTEGER, 
    output_tokens INTEGER, 
    cost_usd NUMERIC(16, 8), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE, 
    FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE SET NULL
);

CREATE INDEX ix_llm_usage_dept_created ON llm_usage (department, created_at);

ALTER TABLE conversation_messages ADD COLUMN investigation_id UUID;

ALTER TABLE conversation_messages ADD CONSTRAINT fk_message_investigation FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE SET NULL;

ALTER TABLE conversation_messages ADD COLUMN simulated BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE conversation_messages ALTER COLUMN simulated DROP DEFAULT;

ALTER TABLE evidence ADD COLUMN investigation_id UUID;

ALTER TABLE evidence ADD CONSTRAINT fk_evidence_investigation FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE SET NULL;

UPDATE alembic_version SET version_num='0002_agent_workflows' WHERE alembic_version.version_num = '0001_initial';

INFO  [alembic.runtime.migration] Running upgrade 0002_agent_workflows -> 0003_demo_mark_price, Track simulated current prices for demo portfolio positions.
INFO  [alembic.runtime.migration] Running upgrade 0002_agent_workflows -> 0003_demo_mark_price, Track simulated current prices for demo portfolio positions.
-- Running upgrade 0002_agent_workflows -> 0003_demo_mark_price

ALTER TABLE demo_positions ADD COLUMN current_price NUMERIC(24, 12);

UPDATE demo_positions SET current_price = average_price;

UPDATE alembic_version SET version_num='0003_demo_mark_price' WHERE alembic_version.version_num = '0002_agent_workflows';

INFO  [alembic.runtime.migration] Running upgrade 0003_demo_mark_price -> 0004_trading_chats, Add switchable Trading Room chats and associate prior messages.
INFO  [alembic.runtime.migration] Running upgrade 0003_demo_mark_price -> 0004_trading_chats, Add switchable Trading Room chats and associate prior messages.
-- Running upgrade 0003_demo_mark_price -> 0004_trading_chats

CREATE TABLE trading_chats (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    title VARCHAR(120) DEFAULT 'New chat' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE
);

CREATE INDEX ix_trading_chat_session_updated ON trading_chats (session_id, updated_at);

ALTER TABLE conversation_messages ADD COLUMN chat_id UUID;

ALTER TABLE investigations ADD COLUMN chat_id UUID;

ALTER TABLE conversation_messages ADD CONSTRAINT fk_message_trading_chat FOREIGN KEY(chat_id) REFERENCES trading_chats (id) ON DELETE CASCADE;

ALTER TABLE investigations ADD CONSTRAINT fk_investigation_trading_chat FOREIGN KEY(chat_id) REFERENCES trading_chats (id) ON DELETE CASCADE;

INSERT INTO trading_chats (id, session_id, title, created_at, updated_at)
      SELECT gen_random_uuid(), session_id, 'Previous chat', min(created_at), max(created_at)
      FROM conversation_messages
      WHERE department='trading' AND session_id IS NOT NULL
      GROUP BY session_id;

UPDATE conversation_messages m SET chat_id=c.id
      FROM trading_chats c
      WHERE m.department='trading' AND m.session_id=c.session_id;

UPDATE investigations i SET chat_id=c.id
      FROM trading_chats c
      WHERE i.department='trading' AND i.session_id=c.session_id;

UPDATE alembic_version SET version_num='0004_trading_chats' WHERE alembic_version.version_num = '0003_demo_mark_price';

INFO  [alembic.runtime.migration] Running upgrade 0004_trading_chats -> 0005_chat_attachments, Store bounded text attachments on Trading Room messages.
INFO  [alembic.runtime.migration] Running upgrade 0004_trading_chats -> 0005_chat_attachments, Store bounded text attachments on Trading Room messages.
-- Running upgrade 0004_trading_chats -> 0005_chat_attachments

ALTER TABLE conversation_messages ADD COLUMN attachments JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE conversation_messages ALTER COLUMN attachments DROP DEFAULT;

UPDATE alembic_version SET version_num='0005_chat_attachments' WHERE alembic_version.version_num = '0004_trading_chats';

INFO  [alembic.runtime.migration] Running upgrade 0005_chat_attachments -> 0006_chat_scoped_agent_memory, Scope Trading Room agent memory to its owning chat.
INFO  [alembic.runtime.migration] Running upgrade 0005_chat_attachments -> 0006_chat_scoped_agent_memory, Scope Trading Room agent memory to its owning chat.
-- Running upgrade 0005_chat_attachments -> 0006_chat_scoped_agent_memory

ALTER TABLE agent_memories ADD COLUMN chat_id UUID;

ALTER TABLE agent_memories ADD CONSTRAINT fk_agent_memory_trading_chat FOREIGN KEY(chat_id) REFERENCES trading_chats (id) ON DELETE CASCADE;

CREATE INDEX ix_agent_memory_chat_agent_created ON agent_memories (chat_id, agent_id, created_at);

UPDATE alembic_version SET version_num='0006_chat_scoped_agent_memory' WHERE alembic_version.version_num = '0005_chat_attachments';

INFO  [alembic.runtime.migration] Running upgrade 0006_chat_scoped_agent_memory -> 0007_wallet_identity, Add verified wallet identities and single-use wallet challenges.
INFO  [alembic.runtime.migration] Running upgrade 0006_chat_scoped_agent_memory -> 0007_wallet_identity, Add verified wallet identities and single-use wallet challenges.
-- Running upgrade 0006_chat_scoped_agent_memory -> 0007_wallet_identity

CREATE TABLE users (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE wallet_identities (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    chain VARCHAR(16) NOT NULL, 
    address VARCHAR(128) NOT NULL, 
    wallet_name VARCHAR(64) NOT NULL, 
    verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_wallet_identity_chain_address UNIQUE (chain, address), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_wallet_identity_user ON wallet_identities (user_id);

CREATE TABLE wallet_challenges (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    chain VARCHAR(16) NOT NULL, 
    address VARCHAR(128) NOT NULL, 
    message TEXT NOT NULL, 
    nonce_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    consumed_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE, 
    UNIQUE (nonce_hash)
);

CREATE INDEX ix_wallet_challenge_session_expiry ON wallet_challenges (session_id, expires_at);

ALTER TABLE browser_sessions ADD COLUMN user_id UUID;

ALTER TABLE browser_sessions ADD CONSTRAINT fk_browser_session_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL;

CREATE INDEX ix_browser_sessions_user_id ON browser_sessions (user_id);

UPDATE alembic_version SET version_num='0007_wallet_identity' WHERE alembic_version.version_num = '0006_chat_scoped_agent_memory';

INFO  [alembic.runtime.migration] Running upgrade 0007_wallet_identity -> 0008_user_paper_ledger, Add isolated USD paper accounts, positions and idempotent orders.
INFO  [alembic.runtime.migration] Running upgrade 0007_wallet_identity -> 0008_user_paper_ledger, Add isolated USD paper accounts, positions and idempotent orders.
-- Running upgrade 0007_wallet_identity -> 0008_user_paper_ledger

CREATE TABLE paper_accounts (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    initial_cash_usd NUMERIC(20, 2) DEFAULT '10000' NOT NULL, 
    cash_usd NUMERIC(20, 8) DEFAULT '10000' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (user_id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE paper_positions (
    id UUID NOT NULL, 
    account_id UUID NOT NULL, 
    chain VARCHAR(16) NOT NULL, 
    token_address VARCHAR(128) NOT NULL, 
    symbol VARCHAR(48) NOT NULL, 
    quantity NUMERIC(36, 16) NOT NULL, 
    average_price_usd NUMERIC(30, 16) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_paper_position_token UNIQUE (account_id, chain, token_address), 
    FOREIGN KEY(account_id) REFERENCES paper_accounts (id) ON DELETE CASCADE
);

CREATE INDEX ix_paper_positions_account_id ON paper_positions (account_id);

CREATE TABLE paper_orders (
    id UUID NOT NULL, 
    account_id UUID NOT NULL, 
    idempotency_key VARCHAR(96) NOT NULL, 
    chain VARCHAR(16) NOT NULL, 
    token_address VARCHAR(128) NOT NULL, 
    symbol VARCHAR(48) NOT NULL, 
    side VARCHAR(8) NOT NULL, 
    amount_usd NUMERIC(20, 8) NOT NULL, 
    price_usd NUMERIC(30, 16) NOT NULL, 
    quantity NUMERIC(36, 16) NOT NULL, 
    source VARCHAR(128) NOT NULL, 
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_paper_order_idempotency UNIQUE (account_id, idempotency_key), 
    FOREIGN KEY(account_id) REFERENCES paper_accounts (id) ON DELETE CASCADE
);

CREATE INDEX ix_paper_orders_account_id ON paper_orders (account_id);

UPDATE alembic_version SET version_num='0008_user_paper_ledger' WHERE alembic_version.version_num = '0007_wallet_identity';

INFO  [alembic.runtime.migration] Running upgrade 0008_user_paper_ledger -> 0009_account_chat_owner, Scope private Trading Room chats to the verified wallet account.
INFO  [alembic.runtime.migration] Running upgrade 0008_user_paper_ledger -> 0009_account_chat_owner, Scope private Trading Room chats to the verified wallet account.
-- Running upgrade 0008_user_paper_ledger -> 0009_account_chat_owner

ALTER TABLE trading_chats ADD COLUMN user_id UUID;

ALTER TABLE trading_chats ADD CONSTRAINT fk_trading_chat_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE;

CREATE INDEX ix_trading_chats_user_id ON trading_chats (user_id);

UPDATE trading_chats AS c SET user_id = s.user_id FROM browser_sessions AS s WHERE c.session_id = s.id AND s.user_id IS NOT NULL;

UPDATE alembic_version SET version_num='0009_account_chat_owner' WHERE alembic_version.version_num = '0008_user_paper_ledger';

INFO  [alembic.runtime.migration] Running upgrade 0009_account_chat_owner -> 0010_investigation_owner, Bind private Trading Room investigations to the verified account.
INFO  [alembic.runtime.migration] Running upgrade 0009_account_chat_owner -> 0010_investigation_owner, Bind private Trading Room investigations to the verified account.
-- Running upgrade 0009_account_chat_owner -> 0010_investigation_owner

ALTER TABLE investigations ADD COLUMN user_id UUID;

ALTER TABLE investigations ADD CONSTRAINT fk_investigation_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE;

CREATE INDEX ix_investigations_user_id ON investigations (user_id);

UPDATE investigations AS i SET user_id = s.user_id FROM browser_sessions AS s WHERE i.session_id = s.id AND i.department = 'trading' AND s.user_id IS NOT NULL;

UPDATE alembic_version SET version_num='0010_investigation_owner' WHERE alembic_version.version_num = '0009_account_chat_owner';

COMMIT;

