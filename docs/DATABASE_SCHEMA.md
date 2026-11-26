# Database schema

PostgreSQL is the active application's only database. `backend/app/models.py` defines the SQLAlchemy 2.x mappings; Alembic owns schema changes. The active application has no persisted evidence-blob table. Provider observations are short-lived in memory. Analysis findings, chat messages, forecast documents, model usage, account data, and durable workflow events remain application records.

| Table family | Purpose | Retention notes |
|---|---|---|
| Browser sessions, users, wallet identities and challenges | Wallet-signature identity and browser sessions | Challenges expire and are single use. Private rows are account scoped. |
| Conversation messages and trading chats | War Room history and private Trading Room chat | Message content persists until a database reset or application retention policy. |
| Investigations, findings, debate rounds and forecasts | Analysis conclusions and forecast records | These are derived outputs; raw provider evidence blobs and evidence IDs are not retained. |
| Durable events, jobs, schedules and provider budgets | Realtime history, bounded background work, schedule state and usage counters | Event/job payloads must not contain source evidence blobs or external guest response text. |
| Paper accounts, positions, orders and transfers | User-owned virtual USDC portfolio | Paper ledger only; no blockchain transaction is created. |
| Watchlists, alerts and Telegram link/outbox records | User-configured notifications and monitored addresses | Account scoped; Telegram tokens remain in environment configuration. |

Historical migration files retain immutable revision IDs for compatibility. Clean installs no longer create evidence/demo trading tables. `0027_clear_existing_data` truncates public application tables, preserves the Alembic revision record, drops legacy simulation columns/tables, and is intentionally irreversible.

## Migration commands

```powershell
alembic upgrade head
alembic current
alembic history
```

Migration `0027_clear_existing_data` destroys existing application rows when applied. It is included because the owner explicitly requested a complete database clear. It has not run in this session because the Docker engine was inaccessible. Do not report the live database as cleared until the migration completes and row counts are checked.

## Wallet identity model

EVM EIP-191 and Solana Ed25519 signatures verify wallet ownership. The virtual portfolio starts with a Zecto ledger allocation and does not use the connected wallet's on-chain funds. Wallet extensions retain their own keys. No paper trade is signed or broadcast.
