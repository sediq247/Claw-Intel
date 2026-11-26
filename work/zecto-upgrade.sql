BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

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

INSERT INTO alembic_version (version_num) VALUES ('0001_initial') RETURNING alembic_version.version_num;

-- Running upgrade 0001_initial -> 0002_agent_workflows

CREATE TABLE investigations (
    id UUID NOT NULL, 
    department VARCHAR(20) NOT NULL, 
    session_id UUID, 
    chain VARCHAR(48) NOT NULL, 
    token_address VARCHAR(160) NOT NULL, 
    title VARCHAR(200) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
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

UPDATE alembic_version SET version_num='0002_agent_workflows' WHERE alembic_version.version_num = '0001_initial';

-- Running upgrade 0002_agent_workflows -> 0003_demo_mark_price

UPDATE alembic_version SET version_num='0003_demo_mark_price' WHERE alembic_version.version_num = '0002_agent_workflows';

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

-- Running upgrade 0004_trading_chats -> 0005_chat_attachments

ALTER TABLE conversation_messages ADD COLUMN attachments JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE conversation_messages ALTER COLUMN attachments DROP DEFAULT;

UPDATE alembic_version SET version_num='0005_chat_attachments' WHERE alembic_version.version_num = '0004_trading_chats';

-- Running upgrade 0005_chat_attachments -> 0006_chat_scoped_agent_memory

ALTER TABLE agent_memories ADD COLUMN chat_id UUID;

ALTER TABLE agent_memories ADD CONSTRAINT fk_agent_memory_trading_chat FOREIGN KEY(chat_id) REFERENCES trading_chats (id) ON DELETE CASCADE;

CREATE INDEX ix_agent_memory_chat_agent_created ON agent_memories (chat_id, agent_id, created_at);

UPDATE alembic_version SET version_num='0006_chat_scoped_agent_memory' WHERE alembic_version.version_num = '0005_chat_attachments';

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

-- Running upgrade 0008_user_paper_ledger -> 0009_account_chat_owner

ALTER TABLE trading_chats ADD COLUMN user_id UUID;

ALTER TABLE trading_chats ADD CONSTRAINT fk_trading_chat_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE;

CREATE INDEX ix_trading_chats_user_id ON trading_chats (user_id);

UPDATE trading_chats AS c SET user_id = s.user_id FROM browser_sessions AS s WHERE c.session_id = s.id AND s.user_id IS NOT NULL;

UPDATE alembic_version SET version_num='0009_account_chat_owner' WHERE alembic_version.version_num = '0008_user_paper_ledger';

-- Running upgrade 0009_account_chat_owner -> 0010_investigation_owner

ALTER TABLE investigations ADD COLUMN user_id UUID;

ALTER TABLE investigations ADD CONSTRAINT fk_investigation_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE;

CREATE INDEX ix_investigations_user_id ON investigations (user_id);

UPDATE investigations AS i SET user_id = s.user_id FROM browser_sessions AS s WHERE i.session_id = s.id AND i.department = 'trading' AND s.user_id IS NOT NULL;

UPDATE alembic_version SET version_num='0010_investigation_owner' WHERE alembic_version.version_num = '0009_account_chat_owner';

-- Running upgrade 0010_investigation_owner -> 0011_watchlists_alerts

CREATE TABLE watchlist_entries (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    chain VARCHAR(16) NOT NULL, 
    token_address VARCHAR(128) NOT NULL, 
    label VARCHAR(80) DEFAULT '' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_watchlist_user_token UNIQUE (user_id, chain, token_address), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_watchlist_user_created ON watchlist_entries (user_id, created_at);

CREATE TABLE price_alerts (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    watchlist_entry_id UUID NOT NULL, 
    chain VARCHAR(16) NOT NULL, 
    token_address VARCHAR(128) NOT NULL, 
    condition VARCHAR(8) NOT NULL, 
    threshold_usd NUMERIC(30, 16) NOT NULL, 
    enabled BOOLEAN DEFAULT true NOT NULL, 
    is_triggered BOOLEAN DEFAULT false NOT NULL, 
    last_observed_price_usd NUMERIC(30, 16), 
    last_checked_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_price_alert_condition CHECK (condition IN ('above', 'below')), 
    CONSTRAINT ck_price_alert_threshold_positive CHECK (threshold_usd > 0), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(watchlist_entry_id) REFERENCES watchlist_entries (id) ON DELETE CASCADE
);

CREATE INDEX ix_price_alerts_user_enabled ON price_alerts (user_id, enabled);

CREATE TABLE price_alert_events (
    id UUID NOT NULL, 
    alert_id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    observed_price_usd NUMERIC(30, 16) NOT NULL, 
    source VARCHAR(128) NOT NULL, 
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    read_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(alert_id) REFERENCES price_alerts (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_price_alert_events_user_created ON price_alert_events (user_id, created_at);

UPDATE alembic_version SET version_num='0011_watchlists_alerts' WHERE alembic_version.version_num = '0010_investigation_owner';

-- Running upgrade 0011_watchlists_alerts -> 0012_telegram_outbox

CREATE TABLE telegram_accounts (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    chat_id VARCHAR(64) NOT NULL, 
    username VARCHAR(64), 
    linked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (user_id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    UNIQUE (chat_id)
);

CREATE TABLE telegram_link_challenges (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    UNIQUE (token_hash)
);

CREATE INDEX ix_telegram_challenge_user_created ON telegram_link_challenges (user_id, created_at);

CREATE TABLE telegram_outbox (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    chat_id VARCHAR(64) NOT NULL, 
    text VARCHAR(4096) NOT NULL, 
    status VARCHAR(20) DEFAULT 'pending' NOT NULL, 
    attempts INTEGER DEFAULT '0' NOT NULL, 
    available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    locked_at TIMESTAMP WITH TIME ZONE, 
    last_error VARCHAR(200), 
    sent_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_telegram_outbox_status_available ON telegram_outbox (status, available_at);

UPDATE alembic_version SET version_num='0012_telegram_outbox' WHERE alembic_version.version_num = '0011_watchlists_alerts';

-- Running upgrade 0012_telegram_outbox -> 0013_distributed_rate_limits

CREATE TABLE rate_limit_buckets (
    route VARCHAR(128) NOT NULL, 
    client_key VARCHAR(64) NOT NULL, 
    window_start TIMESTAMP WITH TIME ZONE NOT NULL, 
    hits INTEGER NOT NULL, 
    CONSTRAINT pk_rate_limit_buckets PRIMARY KEY (route, client_key, window_start), 
    CONSTRAINT ck_rate_limit_buckets_hits_positive CHECK (hits > 0)
);

CREATE INDEX ix_rate_limit_buckets_window_start ON rate_limit_buckets (window_start);

UPDATE alembic_version SET version_num='0013_distributed_rate_limits' WHERE alembic_version.version_num = '0012_telegram_outbox';

-- Running upgrade 0013_distributed_rate_limits -> 0014_durable_agent_jobs

CREATE TABLE agent_jobs (
    id UUID NOT NULL, 
    job_type VARCHAR(40) NOT NULL, 
    dedupe_key VARCHAR(128), 
    payload JSONB NOT NULL, 
    result JSONB, 
    status VARCHAR(20) DEFAULT 'queued' NOT NULL, 
    attempts INTEGER DEFAULT '0' NOT NULL, 
    max_attempts INTEGER DEFAULT '3' NOT NULL, 
    available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    locked_at TIMESTAMP WITH TIME ZONE, 
    last_error VARCHAR(500), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_agent_jobs_attempt_counts CHECK (attempts >= 0 AND max_attempts > 0), 
    CONSTRAINT ck_agent_jobs_status CHECK (status IN ('queued','processing','retrying','completed','dead')), 
    UNIQUE (dedupe_key)
);

CREATE INDEX ix_agent_jobs_status_available ON agent_jobs (status, available_at);

CREATE INDEX ix_agent_jobs_status_locked ON agent_jobs (status, locked_at);

UPDATE alembic_version SET version_num='0014_durable_agent_jobs' WHERE alembic_version.version_num = '0013_distributed_rate_limits';

-- Running upgrade 0014_durable_agent_jobs -> 0015_virtual_sol_wallet

ALTER TABLE paper_accounts ADD COLUMN initial_virtual_sol NUMERIC(24, 9) DEFAULT '10000' NOT NULL;

ALTER TABLE paper_accounts ADD COLUMN virtual_sol_balance NUMERIC(24, 9) DEFAULT '10000' NOT NULL;

UPDATE alembic_version SET version_num='0015_virtual_sol_wallet' WHERE alembic_version.version_num = '0014_durable_agent_jobs';

-- Running upgrade 0015_virtual_sol_wallet -> 0016_virtual_usdc_wallet

ALTER TABLE paper_accounts ADD COLUMN initial_virtual_usdc NUMERIC(24, 6) DEFAULT '10000' NOT NULL;

ALTER TABLE paper_accounts ADD COLUMN virtual_usdc_balance NUMERIC(24, 6) DEFAULT '10000' NOT NULL;

UPDATE alembic_version SET version_num='0016_virtual_usdc_wallet' WHERE alembic_version.version_num = '0015_virtual_sol_wallet';

-- Running upgrade 0016_virtual_usdc_wallet -> 0017_virtual_usdc_transfers

CREATE TABLE paper_transfers (
    id UUID NOT NULL, 
    idempotency_key VARCHAR(96) NOT NULL, 
    sender_account_id UUID NOT NULL, 
    recipient_account_id UUID NOT NULL, 
    amount_usdc NUMERIC(24, 6) NOT NULL, 
    recipient_chain VARCHAR(16) NOT NULL, 
    recipient_address VARCHAR(128) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_paper_transfer_idempotency UNIQUE (sender_account_id, idempotency_key), 
    CONSTRAINT ck_paper_transfer_positive_amount CHECK (amount_usdc > 0), 
    CONSTRAINT ck_paper_transfer_distinct_accounts CHECK (sender_account_id <> recipient_account_id), 
    FOREIGN KEY(sender_account_id) REFERENCES paper_accounts (id) ON DELETE CASCADE, 
    FOREIGN KEY(recipient_account_id) REFERENCES paper_accounts (id) ON DELETE CASCADE
);

CREATE INDEX ix_paper_transfer_sender_created ON paper_transfers (sender_account_id, created_at);

CREATE INDEX ix_paper_transfer_recipient_created ON paper_transfers (recipient_account_id, created_at);

UPDATE alembic_version SET version_num='0017_virtual_usdc_transfers' WHERE alembic_version.version_num = '0016_virtual_usdc_wallet';

-- Running upgrade 0017_virtual_usdc_transfers -> 0018_autonomous_schedule

CREATE INDEX ix_evidence_dept_kind_chain_address ON evidence (department, data_kind, chain, token_address);

CREATE TABLE autonomous_schedule (
    id SERIAL NOT NULL, 
    phase VARCHAR(12) NOT NULL, 
    phase_started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    phase_ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    next_scan_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    next_ambient_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_news_url VARCHAR(1000), 
    rugged_tokens_7d INTEGER, 
    rugcheck_updated_at TIMESTAMP WITH TIME ZONE, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_autonomous_schedule_singleton CHECK (id = 1), 
    CONSTRAINT ck_autonomous_schedule_phase CHECK (phase IN ('working','draining','resting'))
);

UPDATE alembic_version SET version_num='0018_autonomous_schedule' WHERE alembic_version.version_num = '0017_virtual_usdc_transfers';

-- Running upgrade 0018_autonomous_schedule -> 0019_market_forecasts

CREATE TABLE market_forecasts (
    id UUID NOT NULL, 
    investigation_id UUID NOT NULL, 
    asset_class VARCHAR(24) DEFAULT 'crypto' NOT NULL, 
    asset_key VARCHAR(240) NOT NULL, 
    symbol VARCHAR(64) NOT NULL, 
    version INTEGER NOT NULL, 
    provider VARCHAR(32) NOT NULL, 
    model VARCHAR(160) NOT NULL, 
    forecast JSONB NOT NULL, 
    supersedes_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_market_forecast_asset_version UNIQUE (asset_key, version), 
    FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE CASCADE, 
    FOREIGN KEY(supersedes_id) REFERENCES market_forecasts (id) ON DELETE SET NULL
);

CREATE INDEX ix_market_forecast_asset_created ON market_forecasts (asset_key, created_at);

CREATE INDEX ix_market_forecast_investigation ON market_forecasts (investigation_id);

UPDATE alembic_version SET version_num='0019_market_forecasts' WHERE alembic_version.version_num = '0018_autonomous_schedule';

-- Running upgrade 0019_market_forecasts -> 0020_stock_observations

CREATE TABLE stock_observations (
    id UUID NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    market_date DATE NOT NULL, 
    open_usd NUMERIC(24, 8) NOT NULL, 
    high_usd NUMERIC(24, 8) NOT NULL, 
    low_usd NUMERIC(24, 8) NOT NULL, 
    close_usd NUMERIC(24, 8) NOT NULL, 
    volume NUMERIC(30, 0) NOT NULL, 
    source VARCHAR(80) DEFAULT 'Alpha Vantage Daily Adjusted' NOT NULL, 
    retrieved_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_stock_observation_symbol_date UNIQUE (symbol, market_date)
);

UPDATE alembic_version SET version_num='0020_stock_observations' WHERE alembic_version.version_num = '0019_market_forecasts';

-- Running upgrade 0020_stock_observations -> 0021_provider_daily_budgets

CREATE TABLE provider_daily_budgets (
    provider VARCHAR(40) NOT NULL, 
    budget_date DATE NOT NULL, 
    request_count INTEGER DEFAULT '0' NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_provider_daily_budgets PRIMARY KEY (provider, budget_date), 
    CONSTRAINT ck_provider_daily_budget_nonnegative CHECK (request_count >= 0)
);

UPDATE alembic_version SET version_num='0021_provider_daily_budgets' WHERE alembic_version.version_num = '0020_stock_observations';

-- Running upgrade 0021_provider_daily_budgets -> 0022_hourly_market_phases

ALTER TABLE autonomous_schedule DROP CONSTRAINT ck_autonomous_schedule_phase;

UPDATE autonomous_schedule
        SET phase = CASE
                WHEN EXTRACT(MINUTE FROM timezone('UTC', now())) < 15 THEN 'crypto'
                WHEN EXTRACT(MINUTE FROM timezone('UTC', now())) < 30 THEN 'resting'
                WHEN EXTRACT(MINUTE FROM timezone('UTC', now())) < 45 THEN 'stocks'
                ELSE 'idle'
            END,
            phase_started_at = (date_trunc('hour', timezone('UTC', now()))
                + floor(EXTRACT(MINUTE FROM timezone('UTC', now())) / 15) * interval '15 minutes') AT TIME ZONE 'UTC',
            phase_ends_at = (date_trunc('hour', timezone('UTC', now()))
                + (floor(EXTRACT(MINUTE FROM timezone('UTC', now())) / 15) + 1) * interval '15 minutes') AT TIME ZONE 'UTC';

ALTER TABLE autonomous_schedule ADD CONSTRAINT ck_autonomous_schedule_phase CHECK (phase IN ('crypto','resting','stocks','idle'));

UPDATE alembic_version SET version_num='0022_hourly_market_phases' WHERE alembic_version.version_num = '0021_provider_daily_budgets';

-- Running upgrade 0022_hourly_market_phases -> 0023_a2a_reception_queue

CREATE TABLE a2a_reception_requests (
    id UUID NOT NULL, 
    session_started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    requester_session_id UUID NOT NULL, 
    configured_url VARCHAR(600) NOT NULL, 
    endpoint VARCHAR(600) NOT NULL, 
    guest_name VARCHAR(120) NOT NULL, 
    guest_description VARCHAR(500) DEFAULT '' NOT NULL, 
    capabilities JSONB DEFAULT '[]' NOT NULL, 
    question TEXT NOT NULL, 
    status VARCHAR(20) DEFAULT 'queued' NOT NULL, 
    trust_state VARCHAR(40) DEFAULT 'operator_allowlisted_unverified' NOT NULL, 
    screening JSONB DEFAULT '{}' NOT NULL, 
    rejection_reason VARCHAR(200), 
    response JSONB, 
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    admitted_at TIMESTAMP WITH TIME ZONE, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_a2a_reception_status CHECK (status IN ('queued','admitted','completed','failed','dismissed','rejected','expired')), 
    FOREIGN KEY(requester_session_id) REFERENCES browser_sessions (id) ON DELETE CASCADE, 
    CONSTRAINT uq_a2a_guest_per_session UNIQUE (session_started_at, configured_url)
);

CREATE INDEX ix_a2a_reception_session_status_queued ON a2a_reception_requests (session_started_at, status, queued_at);

UPDATE alembic_version SET version_num='0023_a2a_reception_queue' WHERE alembic_version.version_num = '0022_hourly_market_phases';

-- Running upgrade 0023_a2a_reception_queue -> 0024_remove_persisted_evidence

UPDATE conversation_messages
        SET attachments = COALESCE((
            SELECT jsonb_agg(item - 'evidence_ids')
            FROM jsonb_array_elements(attachments) AS item
        ), '[]'::jsonb)
        WHERE attachments::text LIKE '%evidence_ids%';

UPDATE durable_events
        SET payload = payload - 'evidence_id' - 'evidence_ids'
        WHERE payload ? 'evidence_id' OR payload ? 'evidence_ids';

UPDATE agent_jobs
        SET status = 'dead', completed_at = now(), locked_at = NULL,
            last_error = 'Discarded because raw evidence is no longer retained',
            payload = payload - 'evidence_id'
        WHERE payload ? 'evidence_id' AND status IN ('queued','processing','retrying');

UPDATE agent_jobs
        SET payload = payload - 'evidence_id' - 'evidence_ids',
            result = CASE WHEN result IS NULL THEN NULL
                          ELSE result - 'evidence_id' - 'evidence_ids' END
        WHERE payload ? 'evidence_id' OR payload ? 'evidence_ids'
           OR result ? 'evidence_id' OR result ? 'evidence_ids';

UPDATE market_forecasts
        SET forecast = forecast - 'supporting_evidence_ids' - 'contradicting_evidence_ids'
        WHERE forecast ? 'supporting_evidence_ids' OR forecast ? 'contradicting_evidence_ids';

ALTER TABLE market_forecasts DROP CONSTRAINT IF EXISTS market_forecasts_evidence_id_fkey;

ALTER TABLE market_forecasts DROP COLUMN IF EXISTS evidence_id;

ALTER TABLE market_forecasts DROP COLUMN IF EXISTS source_snapshot;

ALTER TABLE investigation_findings DROP COLUMN IF EXISTS evidence_ids;

DROP TABLE IF EXISTS evidence;

UPDATE alembic_version SET version_num='0024_remove_persisted_evidence' WHERE alembic_version.version_num = '0023_a2a_reception_queue';

-- Running upgrade 0024_remove_persisted_evidence -> 0025_stock_cache

DROP TABLE stock_observations;

UPDATE alembic_version SET version_num='0025_stock_cache' WHERE alembic_version.version_num = '0024_remove_persisted_evidence';

-- Running upgrade 0025_stock_cache -> 0026_no_a2a_response

UPDATE durable_events
        SET payload = payload - 'response'
        WHERE event_type = 'A2A_GUEST_RESPONSE_RECEIVED' AND payload ? 'response';

ALTER TABLE a2a_reception_requests DROP COLUMN response;

UPDATE alembic_version SET version_num='0026_no_a2a_response' WHERE alembic_version.version_num = '0025_stock_cache';

-- Running upgrade 0026_no_a2a_response -> 0027_clear_existing_data

DO $$
        DECLARE app_table record;
        BEGIN
            FOR app_table IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename <> 'alembic_version'
            LOOP
                EXECUTE format('TRUNCATE TABLE %I.%I RESTART IDENTITY CASCADE', 'public', app_table.tablename);
            END LOOP;
        END $$;;

ALTER TABLE public.investigations DROP COLUMN IF EXISTS scenario_id;

ALTER TABLE public.conversation_messages DROP COLUMN IF EXISTS simulated;

DROP TABLE IF EXISTS public.demo_positions, public.demo_quotes, public.demo_trades, public.demo_wallets CASCADE;

UPDATE alembic_version SET version_num='0027_clear_existing_data' WHERE alembic_version.version_num = '0026_no_a2a_response';

COMMIT;

