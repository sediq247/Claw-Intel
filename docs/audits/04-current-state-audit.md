# ClawIntel current-state audit

Audit date: 2026-11-22  
Scope: source, migrations, frontend, deployment files, tests, and product documentation in this checkout.

## Decision

**The current code is a working, testable prototype; it is not ready for worldwide production use.** The local backend contract suite, frontend production build, Python compilation, and offline Alembic generation pass. Production readiness is not established because database-backed operation, production deployment, live providers/wallets, recovery, load, accessibility, and operational monitoring have not been verified.

Older dated audits remain historical records where they describe prior wallet funding or earlier implementation state. This report reflects the current source checkout.

## What the product currently does

- Serves a React/TypeScript application from a FastAPI backend, with PostgreSQL persistence and Alembic-managed schema.
- Presents a public War Room that discovers candidate tokens across Ethereum, BNB Smart Chain, Base, and Solana using external market feeds, records source/time/limitations, and runs bounded agent investigations when providers are configured. The durable job worker and `0014` migration are present and wired into application startup; earlier audit documents that called this queue absent are stale.
- Offers a private Trading Room behind EVM or Solana message-signature authentication. Verified account ownership scopes chats, investigations, and paper trading.
- Gives a verified account a one-time 10,000 virtual USDC allocation. Paper buys, sells, and swaps use fresh exact-address provider observations; internal USDC transfers require a verified ClawIntel recipient and never touch a blockchain. Fees, slippage, latency, liquidity impact, and tax are not modeled.
- Presents Dashboard tabs for Home, History, and War Room Intel Tokens, plus separate Trading Room, observer-only War Room, and wallet-focused Settings. The War Room uses a persisted PostgreSQL schedule for 2–3 hour work blocks and 30–35 minute pauses. During work blocks, it may use GDELT headline results from an HTTPS publisher allowlist for source-linked, headline-limited agent discussions.
- Includes deterministic simulated scenarios, watchlists/price alerts, Telegram linking/outbox code, shared PostgreSQL rate-limit code, and provider/model fallback. Code presence is not proof of successful live integration.

Several modules that older README text called absent are present in this checkout: durable agent jobs, Telegram link/outbox processing, watchlists/price alerts, and shared PostgreSQL rate-limit counters. Their live delivery, cross-replica behavior, and production abuse controls have not been proven.

## Verification performed

| Check | Result | Limit |
|---|---|---|
| `python -m pytest -q -p no:cacheprovider` using `.venv` | 54 passed | Contract/unit tests; not a live database or provider acceptance run. |
| `npm run build` in `frontend` | Passed; 3,750 modules transformed | Compile/build only; no browser, responsive, keyboard, screen-reader, or wallet-device QA. |
| Python `compileall` | Passed | Syntax/import compilation only. |
| Alembic `upgrade head --sql` | Generated through `0018_autonomous_schedule` | Offline SQL generation does not apply or validate migrations against PostgreSQL. |
| `git diff --check` | Passed with line-ending notices | Does not validate runtime behavior. |
| `docker compose config --quiet` | Returned success | Docker warned its local user config was inaccessible; no container was started. |

Docker Compose parsed successfully, but no service was started. PostgreSQL/API runtime, external providers, and wallet extensions were not reachable for live acceptance checks. Live startup and migration checks could not be run.

## Issues fixed in this audit

1. Added migrations `0016`–`0018` for the virtual-USDC balance, internal paper transfers, and persisted autonomous work/rest scheduling, with an index for War Room scan counts.
2. Added account-locked/idempotent internal transfers and wallet-history/receive UI while labeling their virtual-only boundaries.
3. Added the database leader lock and durable schedule for autonomous work/rest phases, plus current-headline discussions sourced from GDELT and rendered source links.
4. Hardened production configuration validation and synchronized the Docker Compose debate defaults with the configured longer deliberation budget.

## Release blockers still open

- **Database and deployment:** apply the full migration chain to the intended PostgreSQL version, verify startup and schema, exercise concurrent account writes and tenant isolation, and prove backup/restore and rollback. Offline SQL is not live migration evidence.
- **Security and abuse resistance:** independently review wallet challenge origin/session behavior, reverse-proxy rate-limit identity, public scan/scenario abuse controls, privacy/retention, dependency and container policies, and incident response under the actual production topology.
- **Provider and product reliability:** run live provider-failure, quota, stale-data, partial-investigation and cost-budget scenarios. The available market sources do not provide full creator/deployer/holder history or a comprehensive contract audit; the UI must retain those limits.
- **Wallets and ledger:** exercise real EVM and Phantom sign-in, account switching, reconnect/logout, transfer replay/concurrency, order idempotency and stale-price handling on supported devices. External chain transfers and additional wallet families remain unsupported or unverified.
- **Notifications and alerts:** validate Telegram linking, webhook/polling mode, retries, price-alert polling and notification delivery against a live deployment.
- **Operations:** validate external traces, actionable alerts, resource/cost budgets, queue backlog/dead-letter monitoring, database maintenance, disaster recovery, scheduler leader failover, multi-replica deployment, and load capacity. Scheduler/queue multi-replica behavior is code-reviewed and unit-tested only, not deployment-tested.
- **Release QA:** complete browser-based accessibility, mobile/responsive, localization, and end-to-end journey review. The current UI and docs are English-only.

Do not market or deploy this checkout as a production-grade worldwide service until these gates are closed and evidence is recorded against the production environment.

## Repository condition

The worktree was already dirty before this audit, with many modified and untracked source, test, migration, and documentation files. This audit preserved those changes. Review the complete diff before committing or releasing.
