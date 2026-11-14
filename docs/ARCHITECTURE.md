# ClawIntel architecture

## Target runtime boundaries

```text
React / TypeScript
  ├─ War Room (read-only feed; no human message endpoint)
  ├─ Trading Room (backend-confirmed demo session required)
  └─ investigations / portfolio / settings
          │ REST + department/session-scoped WebSocket
FastAPI application
  ├─ auth/session and wallet gate
  ├─ autonomous department (Nova, Atlas, Vega, Echo, Orion)
  ├─ trading department (isolated instances + user context)
  ├─ Makto demo wallet, quotes, risk, approvals, positions
  ├─ provider adapters (LLM, market data)
  └─ typed events → PostgreSQL outbox → authorized subscribers
          │ SQLAlchemy 2.x / Alembic
PostgreSQL (durable records, evidence, conversations, demo ledger, events)
```

## Invariants

- Autonomous War Room and Trading Room have separate LLM credentials, memory, budgets, event subscriptions and orchestration. Trading sessions are keyed by an opaque session/user owner; no broadcast crosses this boundary.
- Only the War Room feed is autonomous and read-only. Trading Room human prompts have an explicit authenticated API and persist to that conversation.
- Makto can prepare a quote and risk report, but only application-validated human approval can update the simulated ledger. Agent text is never executable input.
- A demo wallet is database-backed simulated state, not a NEAR account. Demo quotes, balances and executions are clearly labeled. There are no keys, RPC calls or blockchain transactions.
- Evidence records preserve their provider, observation time, chain, token/pair reference and live/delayed/simulated status. Unknown fields remain unknown.
- Durable event rows are committed before broadcast. WebSockets can replay or deduplicate by event ID; they are not the only event store.
- PostgreSQL migrations are explicit. Startup does not create/drop tables or silently migrate/destroy Mongo data.

## Delivery sequencing

1. Research and repository audit (completed in initial docs).
2. PostgreSQL models, session management, Alembic and a no-data-loss legacy export path.
3. API/lifecycle/event foundations and health/config diagnostics.
4. Provider clients and agent domain services, preserving useful existing analyzers/discovery.
5. React app and API contracts, replacing legacy static UI only when the new app is connected.
6. Demo wallet and Trading Room access gate, then Makto and deterministic lifecycle.
7. Scenarios, automated tests, deployment and a final audit based on observed results.
