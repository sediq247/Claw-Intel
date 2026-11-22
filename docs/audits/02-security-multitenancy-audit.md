# Audit 2 — Security and multi-tenant isolation

Updated: 2026-11-17

## Controls implemented

- Session cookies are HttpOnly, SameSite Strict, seven-day, and Secure when `COOKIE_SECURE=true`. CORS uses explicit configured origins; wallet challenges bind Origin, chain, address, nonce, issue time, and expiry.
- EVM and Solana wallet signatures are verified server-side. Challenges are five-minute and single-use. Login/logout rotates the browser session; no private key or seed phrase is collected.
- `users` owns wallet identities. One unique user-owned paper account contains the $10,000 initial virtual allocation, cash balance, positions, and orders.
- Trading chat reads/deletes validate `TradingChat.user_id`; investigations are user-owned; chat-scoped agent memory is private and persists across session rotation.
- Paper order processing validates fresh provider evidence, checks amounts and quantities, locks the account, checks idempotency, and applies balance/position/order changes transactionally.
- Agent prompts explicitly treat external evidence and attachments as untrusted; temporary agent workspaces have bounded JSON/text files and no shell execution.
- Legacy fixture trading APIs cannot create data and return HTTP 410.

## Tests and unverified controls

- Cryptographic tests cover EVM recovery and Solana Ed25519 signatures with ephemeral keys. Mocked route tests cover challenge replay/session rotation, account-scoped chat deletion, exact-address paper order math, and replay protection contracts.
- No live database is available for concurrent overspend, row-lock, rollback, migration, cross-account IDOR, cookie rotation, or challenge replay persistence tests.
- PostgreSQL row-level security is not configured; all isolation relies on application-level ownership predicates and cookie integrity.
- No multi-worker session revocation/event replay test, public endpoint rate limiter, or abuse throttling is implemented.
- Mobile WalletConnect, extension-origin behavior, account switching, Telegram authentication, and real-device signatures remain untested or unsupported.
- Telegram endpoints and approvals do not exist. Public War Room scans and scenario runners do not yet have a production abuse policy.

## Database reset status

The configured database is `clawintel`. An earlier host-level connection attempt failed password authentication. The user's Compose log later showed its PostgreSQL container healthy, but the app migration failed because two Alembic revision IDs exceeded the version column length. Those IDs have been shortened; a live Compose rerun is still needed. No data reset was performed by this assistant. A user-created dump file has the PostgreSQL custom-archive signature, but the archive listing/restore and post-reset row counts have not been verified; do not claim the database is clean.

## Release decision

Account ownership and core paper-ledger controls are implemented, but live PostgreSQL adversarial/concurrency validation, rate limiting, monitoring, and infrastructure recovery are outstanding. Do not deploy as a production multi-user service until those checks pass.
