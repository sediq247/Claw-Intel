# Audit 3 — Production readiness, resilience and performance

Updated: 2026-11-18

## Checks performed

- Backend: 49 tests passed; Python compilation passed.
- Frontend: TypeScript and Vite production build passed (3,750 modules transformed).
- Alembic offline SQL generation currently passes through `0013_distributed_rate_limits`. User-provided Compose logs exposed overlong revision IDs; those have been shortened. Live migration remains unverified.
- `git diff --check` passed, with only line-ending notices.
- A visual browser review was attempted, but the available automation window resolved to the Codex UI instead of the Edge page; no visual review is claimed.
- User-provided Compose logs show PostgreSQL healthy but expose the migration failure: the 0009 Alembic revision ID exceeded `alembic_version.version_num VARCHAR(32)`. Revision IDs were shortened and the offline chain passes; live Compose retry is pending because Docker's named pipe is not accessible from this assistant shell. No data reset was performed. A user-created custom-format dump exists; its header was checked, but archive listing/restore was not.

## Release blockers

| Area | Status |
|---|---|
| Live DB migration and application startup | Partially verified: current local health reports PostgreSQL and a controlled scenario persisted; exact Alembic head, restore, concurrency, and rollback checks remain unverified. |
| Requested data reset | Not performed; preserve current rows until the backup archive is listed/restored and the exact reset scope is confirmed. Current API-backed PostgreSQL reads/writes are verified. |
| Docker/Compose deployment | Not verified; Docker daemon was unavailable. |
| Provider quotas, outage handling, circuit breakers and distributed rate limits | Shared PostgreSQL limits are implemented in migration 0013; live multi-replica enforcement is unverified. Circuit breakers and quota controls remain unimplemented. |
| Telegram link and alert delivery | Implemented in code with a durable retry outbox; real bot webhook setup and delivery require environment configuration and live verification. Trade approval actions are absent. |
| Watchlists and price alerts | Implemented in code: account-scoped persistence, alert polling, notification events, and UI. Live DB/browser E2E remains unverified. |
| Durable agent job queue, retry schedule and dead-letter processing | Not implemented. |
| Rate limits and HTTP telemetry | Protected route limits use shared PostgreSQL counters; HTTP metrics remain process-local. Cross-replica runtime validation and external traces/alerts remain absent. |
| Load testing | Not performed. |
| Wallet interoperability | Current EVM injected and Phantom flows are not validated on real devices; WalletConnect/mobile, Solflare, Backpack, Meteor/HOT are absent. |
| Paper trading fidelity | Virtual-only; provider-price fills omit fees, slippage, latency, market impact and fresh portfolio valuation. |
| UI/browser QA | Build passed; screenshot, screen-reader, keyboard, and mobile-device QA remain outstanding. |

## Required release sequence

1. Restore access to the correct local PostgreSQL service. Take and verify a `pg_dump`, apply migrations through `0013`, then clear only explicitly authorized application data and verify expected rows while retaining the Alembic schema.
2. Test startup, wallet login, account isolation, concurrent buys/sells, replay/idempotency, logout/cache cleanup, rollback, backup restore, and provider failure against live PostgreSQL.
3. Verify Telegram delivery and watchlist flows live; implement durable agent jobs and production telemetry, then live-verify migration 0013 across replicas.
4. Complete browser responsive/accessibility QA and real wallet/provider end-to-end checks. Validate the Docker/Compose production profile and secrets in the target environment.

## Readiness decision

**Not production ready yet.** The source now implements account-owned wallet-authenticated paper trading and the updated frontend, but database access/reset and multiple required integrations/operations controls remain incomplete. No production deployment is claimed.

## Live service and provider follow-up — 2026-11-18

- The user-started application is reachable at `http://localhost:6548`. `/health` reports `status=ok` and `database=postgresql`; `/api/agents` returns six agent identities, and settings report Gemini configured for both departments. A live listing is not evidence that a configured provider has quota or availability.
- Inspected the Trading Room in a browser: it gates private chat until wallet verification and lists Phantom, MetaMask, Coinbase Wallet, and generic injected EVM. No real wallet was connected or asked to sign. The in-app browser does not expose the user's Edge extension provider, so Phantom injection in the user's Edge profile remains unverified.
- Ran the controlled suspicious-token War Room scenario. Its simulated investigation was persisted to PostgreSQL but ended `partial` with no findings. The running app emitted Gemini HTTP 503 overload and HTTP 429 quota errors.
- Updated local `.env` to prioritize `gemini-3.5-flash-lite` for both departments and allow seven model attempts. Against the currently configured Gemini account, direct source-level Trading Room streaming and War Room non-streaming calls both returned successfully using that model.
- Attempted `docker compose up -d --build app`; the shell was denied access to Docker's Windows named pipe. The live container has not loaded the source/settings change. Rebuild, rerun of the live scenario, actual wallet signing, Telegram delivery, restore validation, durable job processing, distributed rate limits, telemetry alerting, and multi-user load testing remain outstanding. Do not mark production readiness complete.
- Telegram check: the configured bot passed Telegram `getMe` as `@Intels247Bot`; `getWebhookInfo` confirms no webhook and no pending updates. `PUBLIC_BASE_URL` is unset, so local polling mode is selected by the app. No Telegram message was sent; wallet-linked account delivery and incoming updates remain unverified end to end.


- Distributed rate-limit follow-up: added migration `0013_distributed_rate_limits`, an atomic PostgreSQL upsert limiter for session creation, wallet challenge/verify, Trading Room messages/quotes, paper orders, watchlist/price-alert mutations, Telegram linking, and public scenario runs. Client identifiers are HMAC pseudonyms; production now requires a shared RATE_LIMIT_KEY_SECRET of at least 32 characters. Requests fail closed when limiter storage is unavailable. Unit coverage and offline migration generation pass; live cross-replica behavior is unverified because Docker access remains unavailable.
