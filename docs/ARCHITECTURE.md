# Zecto architecture

## Runtime boundaries

```text
React / TypeScript
  ├─ War Room: public, read-only intelligence and evidence
  ├─ Trading Room: authenticated private conversations and paper orders
  ├─ Investigations: War Room history or the signed-in user's history
  ├─ Portfolio: account-owned virtual USDC balance, USD-valued positions and orders
  └─ Settings: wallet identities, providers, health and usage
          │ REST + department/session-scoped WebSocket
FastAPI application
  ├─ signed EVM/Solana wallet challenge auth
  ├─ user-owned chat, investigation and paper-account routes
  ├─ six role-specific agents, bounded debate and chat-scoped memory
  ├─ permission-checked registry for twelve evidence-analysis capabilities
  ├─ immutable forecast versions based on transient observations
  ├─ persisted, bounded A2A reception queue and independent guest worker in the War Room
  ├─ daily historical stock analysis with shared provider budgets and explicit terms gate
  ├─ provider adapters for LLMs and market observations
  └─ analysis results, A2A audit events and ordered event persistence
          │ SQLAlchemy 2.x / Alembic
PostgreSQL (users, wallet identity, chats, virtual ledger, forecasts, events)
```

## Invariants

- War Room and Trading Room use separately configured provider chains and memory scopes. The War Room is read-only; private Trading Room APIs require an authenticated user ID.
- Wallet signatures prove address control only. Login does not request a blockchain transaction. Identity supports injected EVM wallets on Ethereum/BSC/Base and Phantom on Solana.
- Each verified user owns a single paper account initialized with $10,000 virtual USDC. User-approved paper orders use recent exact-address token/USD observations, debit or credit USDC directly, and never submit or sign an on-chain transaction.
- Fees, slippage, latency and liquidity impact are not modeled. Portfolio value is not shown when a fresh provider mark is unavailable.
- Makto can explain the user's paper portfolio but cannot change it from chat. Only an explicit order review can apply virtual ledger changes.
- Provider observations are bounded, sanitized, and passed to agents in memory only. They are discarded after the analysis call. Findings and forecast outputs persist, but provider payloads, evidence records, source snapshots, and evidence-ID references do not.
- The PostgreSQL-backed War Room scheduler uses fixed UTC-aligned 15-minute blocks: crypto (00–15), rest (15–30), stocks (30–45), and idle/refresh (45–60). Early completion does not shift later blocks, and restart recovery derives the current phase from UTC wall time.
- War Room forecasts are schema-validated against the current in-memory observation and appended as immutable analysis outputs. Source payloads and citations are discarded. Forecast outcome scoring is not yet implemented.
- A2A endpoints are operator-configured HTTPS Agent Card URLs. The independent reception queue admits at most two eligible guests per active market block and holds at most seven queued requests. Agent Card identity claims remain unverified. Requests contain public-research questions, responses remain untrusted and are not fed into native-agent dialogue, and no account, portfolio, or Trading Room context is sent.
- Stock-session analysis consumes cached daily OHLCV from configured symbols. Alpha Vantage calls require an explicit `ALPHA_VANTAGE_LICENSE_STATUS`, a key, a shared budget, and use clear historical-data labels.
- Durable event rows are committed before broadcast. Current WebSocket fanout is process-local; multi-worker delivery is not solved by this design.
- Migrations are explicit. Startup does not create/drop schema or implicitly import/delete legacy MongoDB data.

## Release status

The current schema chain reaches `0026_no_a2a_response`. Applying migrations 0024–0026 deletes retained evidence rows, forecast source snapshots and references, persisted stock bars, and stored A2A response text. These migrations have only been generated offline; the live database was unavailable, so historical data removal is not verified. Durable agent jobs, watchlists/price alerts, Telegram linking/outbox code, shared PostgreSQL rate-limit counters, capability registry, forecast versioning, stock-session analysis, and the A2A reception queue are implemented, but live behavior has not been verified. HTTP metrics are process-local; WebSocket fanout is also process-local. Backup/restore, production observability, load, browser accessibility, real wallet-device behavior, live A2A partner interoperability, and live migrations remain release gates. Forecast outcome scoring, rolling one-hour rug-event classification, fully verified A2A identity, the model-facing Nova reception operation, and OS-enforced worker/network isolation remain unsupported.
