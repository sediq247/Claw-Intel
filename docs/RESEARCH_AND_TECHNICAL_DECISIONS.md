# Research and technical decisions

Updated: 2026-11-17. Detailed provider references and statuses are in `docs/PROVIDER_RESEARCH_MATRIX.md`.

## Identity and paper trading

- EVM wallet signatures use EIP-191 with origin-bound, short-lived challenges; Solana uses Ed25519 message signatures. Identity verification is distinct from transaction authorization.
- User IDs own wallet identities, private chats, investigations and one USD virtual paper account. A unique account row receives its $10,000 initial allocation once.
- Paper orders require an exact address and fresh provider-retrieved price, explicit UI confirmation, account lock and atomic cash/position/order persistence. Idempotency prevents duplicate fills. Former fixture ledger routes return HTTP 410.
- Paper fills use observed provider price only; no transaction, key custody, fees, slippage, latency or liquidity impact is modeled. Real execution requires separate provider, wallet, risk and audit design.

## Agents and data trust

- Keep the six role boundaries (Nova, Atlas, Vega, Echo, Makto, Orion) and dynamic challenge/synthesis flow. Improvements should add evidence tools with source, time, coverage and failure metadata instead of widening free-form model authority.
- Agents receive bounded, sanitized evidence and untrusted user attachments. They have no shell or code execution. Makto sees account-owned virtual cash/positions but cannot alter the ledger from chat.
- Trading memory is bounded per chat and persists across browser session rotation. Cross-account memory must remain impossible.

## Provider and chain decisions

- War Room discovery is constrained to Solana, BNB Smart Chain, Base and Ethereum. Trading Room address lookup and paper trading capability are reported separately from on-chain execution.
- DexScreener provides discovery and current observations, not executable quotes. CoinGecko and chain RPC enrichments remain optional and require deployer credentials/provider validation.
- No provider credential, rate agreement, live feed behavior or on-chain write capability was verified during the offline implementation check.
- Meteor/HOT NEAR and mobile wallet dependencies were not added after an integration experiment surfaced high-severity dependency advisories. Reviewed adapters and dependency remediation are required before adding that wallet support.

## Operations and remaining release scope

- PostgreSQL/Alembic is the application source of truth. Migrations through `0010_investigation_owner` generate offline SQL; their IDs fit Alembic's 32-character revision column. Live migration is unverified in this shell because Docker access is denied.
- The legacy MongoDB data migration/export path is separate and is not performed at startup.
- Telegram, watchlists/alerts, durable queues/retries/dead letters, global rate limiting, metrics/traces, backup/restore, load testing, and multi-worker WebSocket fanout remain unimplemented or unverified. See `docs/audits/03-production-readiness-audit.md`.
