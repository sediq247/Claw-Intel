BEGIN;

-- Running downgrade 0027_clear_existing_data -> 0026_no_a2a_response

UPDATE alembic_version SET version_num='0026_no_a2a_response' WHERE alembic_version.version_num = '0027_clear_existing_data';

-- Running downgrade 0026_no_a2a_response -> 0025_stock_cache

ALTER TABLE a2a_reception_requests ADD COLUMN response JSONB;

UPDATE alembic_version SET version_num='0025_stock_cache' WHERE alembic_version.version_num = '0026_no_a2a_response';

-- Running downgrade 0025_stock_cache -> 0024_remove_persisted_evidence

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

UPDATE alembic_version SET version_num='0024_remove_persisted_evidence' WHERE alembic_version.version_num = '0025_stock_cache';

-- Running downgrade 0024_remove_persisted_evidence -> 0023_a2a_reception_queue

UPDATE alembic_version SET version_num='0023_a2a_reception_queue' WHERE alembic_version.version_num = '0024_remove_persisted_evidence';

-- Running downgrade 0023_a2a_reception_queue -> 0022_hourly_market_phases

DROP INDEX ix_a2a_reception_session_status_queued;

DROP TABLE a2a_reception_requests;

UPDATE alembic_version SET version_num='0022_hourly_market_phases' WHERE alembic_version.version_num = '0023_a2a_reception_queue';

-- Running downgrade 0022_hourly_market_phases -> 0021_provider_daily_budgets

UPDATE autonomous_schedule SET phase='resting' WHERE phase IN ('crypto','stocks','idle');

ALTER TABLE autonomous_schedule DROP CONSTRAINT ck_autonomous_schedule_phase;

ALTER TABLE autonomous_schedule ADD CONSTRAINT ck_autonomous_schedule_phase CHECK (phase IN ('working','draining','resting'));

UPDATE alembic_version SET version_num='0021_provider_daily_budgets' WHERE alembic_version.version_num = '0022_hourly_market_phases';

-- Running downgrade 0021_provider_daily_budgets -> 0020_stock_observations

DROP TABLE provider_daily_budgets;

UPDATE alembic_version SET version_num='0020_stock_observations' WHERE alembic_version.version_num = '0021_provider_daily_budgets';

-- Running downgrade 0020_stock_observations -> 0019_market_forecasts

DROP TABLE stock_observations;

UPDATE alembic_version SET version_num='0019_market_forecasts' WHERE alembic_version.version_num = '0020_stock_observations';

-- Running downgrade 0019_market_forecasts -> 0018_autonomous_schedule

DROP INDEX ix_market_forecast_investigation;

DROP INDEX ix_market_forecast_asset_created;

DROP TABLE market_forecasts;

UPDATE alembic_version SET version_num='0018_autonomous_schedule' WHERE alembic_version.version_num = '0019_market_forecasts';

-- Running downgrade 0018_autonomous_schedule -> 0017_virtual_usdc_transfers

DROP TABLE autonomous_schedule;

DROP INDEX ix_evidence_dept_kind_chain_address;

UPDATE alembic_version SET version_num='0017_virtual_usdc_transfers' WHERE alembic_version.version_num = '0018_autonomous_schedule';

-- Running downgrade 0017_virtual_usdc_transfers -> 0016_virtual_usdc_wallet

DROP INDEX ix_paper_transfer_recipient_created;

DROP INDEX ix_paper_transfer_sender_created;

DROP TABLE paper_transfers;

UPDATE alembic_version SET version_num='0016_virtual_usdc_wallet' WHERE alembic_version.version_num = '0017_virtual_usdc_transfers';

-- Running downgrade 0016_virtual_usdc_wallet -> 0015_virtual_sol_wallet

ALTER TABLE paper_accounts DROP COLUMN virtual_usdc_balance;

ALTER TABLE paper_accounts DROP COLUMN initial_virtual_usdc;

UPDATE alembic_version SET version_num='0015_virtual_sol_wallet' WHERE alembic_version.version_num = '0016_virtual_usdc_wallet';

-- Running downgrade 0015_virtual_sol_wallet -> 0014_durable_agent_jobs

ALTER TABLE paper_accounts DROP COLUMN virtual_sol_balance;

ALTER TABLE paper_accounts DROP COLUMN initial_virtual_sol;

UPDATE alembic_version SET version_num='0014_durable_agent_jobs' WHERE alembic_version.version_num = '0015_virtual_sol_wallet';

-- Running downgrade 0014_durable_agent_jobs -> 0013_distributed_rate_limits

DROP INDEX ix_agent_jobs_status_locked;

DROP INDEX ix_agent_jobs_status_available;

DROP TABLE agent_jobs;

UPDATE alembic_version SET version_num='0013_distributed_rate_limits' WHERE alembic_version.version_num = '0014_durable_agent_jobs';

-- Running downgrade 0013_distributed_rate_limits -> 0012_telegram_outbox

DROP INDEX ix_rate_limit_buckets_window_start;

DROP TABLE rate_limit_buckets;

UPDATE alembic_version SET version_num='0012_telegram_outbox' WHERE alembic_version.version_num = '0013_distributed_rate_limits';

-- Running downgrade 0012_telegram_outbox -> 0011_watchlists_alerts

DROP INDEX ix_telegram_outbox_status_available;

DROP TABLE telegram_outbox;

DROP INDEX ix_telegram_challenge_user_created;

DROP TABLE telegram_link_challenges;

DROP TABLE telegram_accounts;

UPDATE alembic_version SET version_num='0011_watchlists_alerts' WHERE alembic_version.version_num = '0012_telegram_outbox';

-- Running downgrade 0011_watchlists_alerts -> 0010_investigation_owner

DROP INDEX ix_price_alert_events_user_created;

DROP TABLE price_alert_events;

DROP INDEX ix_price_alerts_user_enabled;

DROP TABLE price_alerts;

DROP INDEX ix_watchlist_user_created;

DROP TABLE watchlist_entries;

UPDATE alembic_version SET version_num='0010_investigation_owner' WHERE alembic_version.version_num = '0011_watchlists_alerts';

-- Running downgrade 0010_investigation_owner -> 0009_account_chat_owner

DROP INDEX ix_investigations_user_id;

ALTER TABLE investigations DROP CONSTRAINT fk_investigation_user;

ALTER TABLE investigations DROP COLUMN user_id;

UPDATE alembic_version SET version_num='0009_account_chat_owner' WHERE alembic_version.version_num = '0010_investigation_owner';

-- Running downgrade 0009_account_chat_owner -> 0008_user_paper_ledger

DROP INDEX ix_trading_chats_user_id;

ALTER TABLE trading_chats DROP CONSTRAINT fk_trading_chat_user;

ALTER TABLE trading_chats DROP COLUMN user_id;

UPDATE alembic_version SET version_num='0008_user_paper_ledger' WHERE alembic_version.version_num = '0009_account_chat_owner';

-- Running downgrade 0008_user_paper_ledger -> 0007_wallet_identity

DROP INDEX ix_paper_orders_account_id;

DROP TABLE paper_orders;

DROP INDEX ix_paper_positions_account_id;

DROP TABLE paper_positions;

DROP TABLE paper_accounts;

UPDATE alembic_version SET version_num='0007_wallet_identity' WHERE alembic_version.version_num = '0008_user_paper_ledger';

-- Running downgrade 0007_wallet_identity -> 0006_chat_scoped_agent_memory

DROP INDEX ix_browser_sessions_user_id;

ALTER TABLE browser_sessions DROP CONSTRAINT fk_browser_session_user;

ALTER TABLE browser_sessions DROP COLUMN user_id;

DROP INDEX ix_wallet_challenge_session_expiry;

DROP TABLE wallet_challenges;

DROP INDEX ix_wallet_identity_user;

DROP TABLE wallet_identities;

DROP TABLE users;

UPDATE alembic_version SET version_num='0006_chat_scoped_agent_memory' WHERE alembic_version.version_num = '0007_wallet_identity';

-- Running downgrade 0006_chat_scoped_agent_memory -> 0005_chat_attachments

DROP INDEX ix_agent_memory_chat_agent_created;

ALTER TABLE agent_memories DROP CONSTRAINT fk_agent_memory_trading_chat;

ALTER TABLE agent_memories DROP COLUMN chat_id;

UPDATE alembic_version SET version_num='0005_chat_attachments' WHERE alembic_version.version_num = '0006_chat_scoped_agent_memory';

-- Running downgrade 0005_chat_attachments -> 0004_trading_chats

ALTER TABLE conversation_messages DROP COLUMN attachments;

UPDATE alembic_version SET version_num='0004_trading_chats' WHERE alembic_version.version_num = '0005_chat_attachments';

-- Running downgrade 0004_trading_chats -> 0003_demo_mark_price

ALTER TABLE investigations DROP CONSTRAINT fk_investigation_trading_chat;

ALTER TABLE conversation_messages DROP CONSTRAINT fk_message_trading_chat;

ALTER TABLE investigations DROP COLUMN chat_id;

ALTER TABLE conversation_messages DROP COLUMN chat_id;

DROP INDEX ix_trading_chat_session_updated;

DROP TABLE trading_chats;

UPDATE alembic_version SET version_num='0003_demo_mark_price' WHERE alembic_version.version_num = '0004_trading_chats';

-- Running downgrade 0003_demo_mark_price -> 0002_agent_workflows

UPDATE alembic_version SET version_num='0002_agent_workflows' WHERE alembic_version.version_num = '0003_demo_mark_price';

-- Running downgrade 0002_agent_workflows -> 0001_initial

ALTER TABLE conversation_messages DROP CONSTRAINT fk_message_investigation;

ALTER TABLE conversation_messages DROP COLUMN investigation_id;

DROP INDEX ix_llm_usage_dept_created;

DROP TABLE llm_usage;

DROP INDEX ix_memory_dept_session_agent_created;

DROP TABLE agent_memories;

DROP TABLE debate_rounds;

DROP INDEX ix_finding_investigation_round;

DROP TABLE investigation_findings;

DROP INDEX ix_investigation_dept_session_updated;

DROP TABLE investigations;

UPDATE alembic_version SET version_num='0001_initial' WHERE alembic_version.version_num = '0002_agent_workflows';

-- Running downgrade 0001_initial -> 

DROP INDEX ix_event_dept_session_sequence;

DROP TABLE durable_events;

DROP INDEX ix_message_session_department_created;

DROP TABLE conversation_messages;

DROP TABLE browser_sessions;

DELETE FROM alembic_version WHERE alembic_version.version_num = '0001_initial';

COMMIT;

