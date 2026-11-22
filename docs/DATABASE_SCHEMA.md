# Database schema

PostgreSQL is the active application's only database. `backend/app/models.py` defines SQLAlchemy 2.x mappings. `backend/app/migrations/versions/0001_initial.py` creates the first Alembic revision. The API intentionally does not create or mutate schema at startup.

| Table | Purpose | Isolation / constraints |
|---|---|---|
| `browser_sessions` | Opaque browser session, with optional authenticated user owner | UUID key; cookie is HttpOnly, Secure when configured, SameSite Strict. Private endpoints require `user_id`. |
| `conversation_messages` | War Room and Trading Room messages | Trading messages are read through an account-owned `trading_chats` record. |
| `evidence` | Market observation and scenario evidence | Source, chain, token, observation time, live/delayed/simulated kind, provider fields and limitations are retained. |
| `investigations` / `investigation_findings` | Evidence review, role findings and debate rounds | Trading investigations have `user_id` ownership; findings load only through owned investigation IDs. War Room findings remain public. |
| `durable_events` | Ordered department and session event history | Sequence key, unique event UUID and department/session index; committed before WebSocket broadcast. |
| `users` | Account owner created after a verified wallet challenge | Wallet identity rows map unique `(chain,address)` keys to one user. |
| `wallet_identities` | Verified EVM/Solana addresses | Unique `(chain,address)`, owned by user. |
| `wallet_challenges` | Short-lived single-use wallet signatures | Session-bound, nonce hash unique, origin-bound challenge, expiry and consumed timestamp. |
| `paper_accounts` | Virtual USDC account with legacy USD and SOL columns retained | Unique per user; active USDC grant/balance are stored once and change under row lock. |
| `paper_positions` | User-owned paper holdings | Account-scoped unique `(chain,token_address)` and decimal quantity/cost. |
| `paper_orders` | Append-only paper order records | Account-scoped unique idempotency key; stores provider, observation time, price, quantity and side. |
| `trading_chats` | Private Trading Room conversations | `user_id` ownership survives browser session rotation; legacy rows may have null owner until migrated or purged. |

Legacy `demo_wallets`, `demo_quotes`, `demo_trades`, and `demo_positions` tables remain in the schema for migration compatibility. Their API write paths return `410 Gone`; the active frontend does not read them. `0015_virtual_sol_wallet` added legacy SOL fields; `0016_virtual_usdc_wallet` adds the active $10,000 virtual USDC grant and balance. Earlier balances are retained for migration history and are not spendable in the current UI.

## Migration commands

```powershell
alembic upgrade head
alembic current
alembic history
```

Take backups before migrations in any existing deployment. MongoDB data from the former application is not imported or deleted by this revision. A production Mongo-to-PostgreSQL migration utility is not yet implemented.

## Local reset

The configured local PostgreSQL service at `localhost:5432` refused connections and Docker was unavailable during earlier verification. No destructive reset was performed. A user-created `clawintel-before-reset.dump` custom-format file is present, but its full archive listing/restore was not verified. For an operator-led reset, verify the archive with `pg_restore -l`, confirm the target database, and check table row counts before and after; never remove an unverified volume.

## Wallet identity model

`0007_wallet_identity` adds wallet auth and `browser_sessions.user_id`; `0008_user_paper_ledger` adds the original USD account, positions and orders; `0009_account_chat_owner` adds user ownership to chats and backfills owners from authenticated sessions; `0010_investigation_owner` adds user ownership and backfills private investigations; `0015_virtual_sol_wallet` adds legacy SOL columns; `0016_virtual_usdc_wallet` adds the active USDC balance. Revision IDs remain within Alembic's 32-character `version_num` limit. EVM EIP-191 recovery uses `eth-account`; Solana signature verification uses PyNaCl Ed25519. Challenge messages bind the configured Origin, address, chain, nonce, issue time and expiry.
