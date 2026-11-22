# ClawIntel architecture

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
  ├─ provider adapters for LLMs and market observations
  └─ evidence and ordered event persistence
          │ SQLAlchemy 2.x / Alembic
PostgreSQL (users, wallet identity, evidence, chats, virtual ledger, events)
```

## Invariants

- War Room and Trading Room use separately configured provider chains and memory scopes. The War Room is read-only; private Trading Room APIs require an authenticated user ID.
- Wallet signatures prove address control only. Login does not request a blockchain transaction. Identity supports injected EVM wallets on Ethereum/BSC/Base and Phantom on Solana.
- Each verified user owns a single paper account initialized with $10,000 virtual USDC. User-approved paper orders use recent exact-address token/USD observations, debit or credit USDC directly, and never submit or sign an on-chain transaction.
- Fees, slippage, latency and liquidity impact are not modeled. Portfolio value is not shown when a fresh provider mark is unavailable.
- Makto can explain the user's paper portfolio but cannot change it from chat. Only an explicit order review can apply virtual ledger changes.
- Evidence retains source, observation time, chain, token, status, fields and limitations. Agents receive bounded sanitized fields as untrusted data and have no shell or code-execution tools.
- Durable event rows are committed before broadcast. Current WebSocket fanout is process-local; multi-worker delivery is not solved by this design.
- Migrations are explicit. Startup does not create/drop schema or implicitly import/delete legacy MongoDB data.

## Release status

The current schema chain reaches `0016_virtual_usdc_wallet`. Durable agent jobs, watchlists/price alerts, Telegram linking/outbox code, and shared PostgreSQL rate-limit counters are implemented, but live behavior has not been verified. HTTP metrics are process-local; WebSocket fanout is also process-local. Backup/restore, production observability, load, browser accessibility, real wallet-device behavior, and live migrations remain release gates. See `docs/audits/04-current-state-audit.md` for the audit baseline before the wallet redesign.
