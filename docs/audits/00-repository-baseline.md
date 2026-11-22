# ClawIntel repository baseline

Date: 2026-11-17
Scope: repository and upgrade-package baseline before application edits in this execution.

## Repository state

- The project is a Python FastAPI service with SQLAlchemy async models/Alembic migrations and a React 19 + TypeScript + Vite frontend. PostgreSQL is the configured database.
- Six agent roles and distinct War Room (`autonomous`) and private Trading Room workflows are present. The current runtime has a real-provider LLM adapter and a DexScreener market-data adapter, with provider provenance/health states.
- The Trading Room is a local demo, not a production wallet or trading account. Browser sessions are anonymous UUID cookies; wallet connection creates a simulated address and seeds 1,000 virtual NEAR. Quotes are fixture-only and short-lived; deterministic demo buys and sells are present. There is no real wallet signature verification, USD ledger, stop/target monitoring, executable market quote, chain registry, or production risk policy.
- Existing tables include browser sessions, trading chats/messages, evidence/investigations/findings/debate rounds, agent memory, LLM usage, durable events, and demo wallet/quote/trade/position records. Schema changes use Alembic.
- Telegram identity/linking, webhook handling, update dedupe, notifications and approvals are absent. Watchlists and alert rules are absent.
- There are no frontend wallet adapter packages or backend EVM/Solana/NEAR signature verification libraries in the declared dependencies.
- Deployment uses Docker Compose/PostgreSQL and documents migration and backup cautions. Current environment has no confirmed live PostgreSQL/Docker service; production migration, deployment, and backup restore cannot be claimed without those services and credentials.

## Pre-existing work and preservation

The worktree was already dirty before this execution. Modified files: `.env.example`, `Readme.MD`, `backend/app/main.py`, `backend/app/market_data.py`, `backend/app/models.py`, `backend/app/orchestration.py`, `backend/app/services.py`, `docker-compose.yml`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/styles.css`, `requirements.txt`, and `tests/test_backend_contracts.py`. Untracked files: `backend/app/agent_sandbox.py`, migrations `0005_chat_attachments.py` and `0006_chat_scoped_agent_memory.py`. These edits are existing project work and are retained; `.env` was not read or copied. No repository `AGENTS.md` was found.

## Baseline checks

- Backend: `python -m pytest -q` — 31 passed. Pytest emitted a cache permission warning; test execution itself passed.
- Frontend: `npm run build` — TypeScript/Vite production build command completed (Vite reported v7.3.7); no live API/database was involved.
- Git working tree was already dirty as documented above. No clean backup branch was created because that would rewrite shared repository Git state; changes are being made in-place while preserving the pre-existing work.

## Migration and rollback approach

- Preserve existing anonymous demo flows and current user edits while adding isolated services/models.
- Use additive Alembic revisions with explicit downgrade paths; do not delete legacy demo records or migrate/drop Mongo data as part of this work.
- For deployment, back up PostgreSQL before applying revisions, inspect generated SQL/current revision, and retain the prior image and DB backup for rollback. A live rollback/restore requires a running PostgreSQL deployment and is not verified in this local environment.

## Baseline exit assessment

Architecture and current behavior are understood well enough to proceed. The current app is a functional local prototype, not the production system described by the upgrade package. Database-backed and external-provider flows require configured runtime services/credentials for end-to-end verification. This report is the Gate 0 baseline; later implementation and audits must distinguish implemented, tested, credential-blocked, and unsupported behavior.
