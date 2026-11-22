# Audit 1 — Functional and architectural integrity

Updated: 2026-11-17

## Implemented and checked

- War Room discovery filters upstream sources to Solana, BNB Smart Chain, Base, and Ethereum before pair lookups.
- Trading Room resolves exact token addresses, returns source/time/limitations, rejects ticker-only input, and exposes a separate virtual paper-order path.
- EVM/Solana sign-in uses single-use, origin-bound challenge signatures. Verified user IDs own chats, investigations, and a one-time $10,000 USD paper account.
- The paper order path checks supported chain/address formats, fetches a fresh exact-address provider observation, serializes changes with the account row lock, enforces cash/position limits, and stores an idempotent order and position change in one transaction.
- The frontend now has account verification, Paper Trading — Virtual Funds controls, account portfolio/order history, and separate public War Room/private investigation views. The former fixture-trade routes return `410 Gone`.
- Makto receives the authenticated user's virtual cash and position context. Chat is not trade approval; an order requires explicit confirmation in the order panel.
- Agent memory follows a private chat across session rotation. Agent investigation prompts ask for source/time provenance and distinguish facts from interpretation.

## Verification

- `python -m pytest -q -o cache_dir=work\pytest-cache` — 38 passed, including Alembic revision ID length.
- `python -m compileall -q backend agents runtime utils server_main.py agents_main.py` — passed.
- `npm run build` — TypeScript and Vite production bundle passed.
- `alembic upgrade head --sql` — offline SQL generated through `0010_investigation_owner` after fixing revision IDs that exceeded Alembic's 32-character version column.
- `git diff --check` — passed; Git reported line-ending notices only.

## Remaining functional gaps

- Telegram account linking and alert notifications now have a one-time deep-link flow, secret-header webhook, and retryable delivery outbox; live bot setup and Telegram approval callbacks remain unverified/absent.
- Wallet-owned watchlists, monitored price thresholds, persisted in-app notifications, and management UI are implemented; live database and browser acceptance remain open.
- The War Room still has two deterministic simulated evidence cases rather than a complete scenario suite.
- Portfolio current valuation is explicitly unavailable until a fresh mark workflow is built; fees, slippage, latency and liquidity impact are not modeled.
- Live PostgreSQL journeys, real wallet extension flows, live provider calls, and responsive browser screenshot review could not be completed in this environment.

The implementation is not a production release until the integration and infrastructure gaps in Audit 3 are closed.
