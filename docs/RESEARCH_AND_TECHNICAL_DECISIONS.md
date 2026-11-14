# Research and technical decisions

Research pass dated 2026-11-05. This is an implementation baseline, not a claim that every feature below is already shipped. Provider models, prices, quotas, wallet support and API fields can change; pin versions and recheck live provider docs before release.

## Summary decisions

- Keep Python for market and agent business logic, but move the HTTP boundary to FastAPI with explicit async lifespan, dependency injection and department/session-scoped WebSockets. The current `aiohttp` server is custom and workable, but its polling-based coupling and unscoped broadcast model are a poor fit for the required authorization boundary.
- Use PostgreSQL as the sole primary store, SQLAlchemy 2.x and Alembic. Use one async session per request/task; never share an `AsyncSession` among concurrent agent tasks. Persistence is a prerequisite for reliable event replay and wallet/trade idempotency.
- Use a React + TypeScript frontend built by Vite. Tailwind is suitable for styling; adopt headless accessible primitives (shadcn/ui source components) selectively. TanStack Query owns remote server state; Zustand is reserved for small ephemeral UI state. Do not duplicate server state in a global store.
- Keep a provider-neutral LLM interface, with an independent configuration, client, priority chain, budget and usage records for each department. Gemini uses Google's `google-genai` SDK; OpenRouter and Cerebras expose OpenAI-compatible chat APIs and can use the maintained `openai` Python SDK with explicit base URLs. Provider calls must fail visibly; no fabricated completion is an acceptable fallback.
- Make the first wallet provider an application-owned deterministic demo ledger. It has no private keys, no signing and no chain RPC. The front end calls the backend to create/recover a demo session; every Trading Room endpoint checks that session server-side. A future real NEAR provider must be a separate adapter and must remain disabled until separately designed and authorized.
- Retain DexScreener as a public market adapter where its documented endpoints fit. Persist source, observation time, chain, token/pair identifiers and raw/normalized provenance. Its current API documents up to 60 requests/minute on token profile/boost endpoints and 300/minute for pair/search/token endpoints. Missing data stays missing; boosts/ads are promotional signals, not organic demand or safety evidence.

## Technology and compatibility notes

| Area | Decision | Evidence and caveats |
|---|---|---|
| React + TypeScript | Use current React with strict TS | React's official docs recommend modern component APIs; TypeScript catches API and state contract drift. |
| Vite | Use `react-ts` template; keep `tsc --noEmit` in build because Vite transpilation alone does not type-check | [Vite guide](https://vite.dev/guide/), [Vite features](https://vite.dev/guide/features.html). Current Vite guide calls for Node 20.19+ or 22.12+. |
| Tailwind / shadcn/ui | Tailwind via its Vite integration; bring in only accessible primitives needed by product | [Tailwind Vite guide](https://tailwindcss.com/docs/installation/using-vite). shadcn components are source code, so their local copies must be reviewed and upgraded deliberately. |
| Routing | React Router (or its current stable framework/library mode) | Keep route protection based on backend wallet-session state; client-side route guards are only UX. |
| Server/client state | TanStack Query for API state; Zustand only for local interaction state | [TanStack Query overview](https://tanstack.com/query/latest/docs/framework/react/overview). WebSocket events should invalidate/update query caches with event IDs for dedupe. |
| Other UI packages | Framer Motion, Lucide, Recharts, React Hook Form + Zod only where the interaction benefits | These are UI conveniences, not architecture dependencies. Respect reduced-motion, keyboard and screen-reader behavior. |
| API | FastAPI + Pydantic v2 | [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/). Typed schemas provide a natural REST/WS contract. Use CORS allowlists and validate WS subscriptions before accepting private events. |
| Database | PostgreSQL + SQLAlchemy 2.x async + Alembic + asyncpg | [SQLAlchemy async docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html). One `AsyncSession` per concurrent task; eager-load relationships to avoid implicit async IO. Alembic migrations are reviewed and explicit; startup must not create/drop production schema. |
| Background work | Begin with asyncio lifespan-managed tasks and PostgreSQL outbox/replay; introduce a broker only after measured need | Redis is not justified for a single process demo. Multi-worker production would require shared durable event distribution and a separate worker lifecycle. |
| PostgreSQL configuration | `DATABASE_URL` secret, validated at startup; local compose service for development | Existing repository is MongoDB/Motor-only. No reliable automatic destructive migration exists; preserve/backup Mongo data before any user-operated migration. |

## LLM provider design

Google documents the Gemini API and official `google-genai` SDK at [Gemini API docs](https://ai.google.dev/gemini-api/docs) and [model catalog](https://ai.google.dev/gemini-api/docs/models). Do not hard-code an old model catalog; require a configured model or a reviewed default and surface model-not-found errors. Capture provider-reported token usage when present. Cost estimates are only shown when current pricing metadata exists.

OpenRouter documents an OpenAI-compatible API at `https://openrouter.ai/api/v1`, model IDs in provider/model form and optional multi-model/provider routing ([platform docs](https://openrouter.ai/developers), [API docs](https://openrouter.ai/docs)). It may apply internal fallback, so record the requested model and actual returned model/provider metadata where available. Do not claim provider-level independence if OpenRouter routed the request elsewhere.

Cerebras documents its Inference API and SDK at [Cerebras docs](https://docs.cerebras.ai/) and [Inference pricing](https://inference-docs.cerebras.ai/support/pricing). Its OpenAI-compatibility is a protocol option, not proof all OpenAI parameters or models are supported. Keep a Cerebras adapter with a deliberately small request shape, configurable model, timeout and bounded retry on transient 429/5xx responses. Read rate-limit headers/provider errors rather than assuming stable quotas.

Configuration contract: `WARROOM_{GEMINI,OPENROUTER,CEREBRAS}_API_KEY`, corresponding model variables and provider order; same for `TRADING_...`. Keys stay server-side. A missing provider is reported as unavailable. There is no successful response on provider failure. Usage is tracked separately by department and includes provider/model, input/output tokens when reported, latency, request outcome and cost only when verifiable.

## NEAR and wallet boundary

NEAR account identifiers and keys form an account-based model; RPC supports account/state and transaction/status operations. The NEAR wallet-selector project provides an adapter over compatible ecosystem wallets ([near/wallet-selector](https://github.com/near/wallet-selector)); the repository labels the project as legacy in current NEAR organization information, so a real-wallet choice must be revalidated against the current recommended wallet API/provider before implementation. NEP-141 is the final fungible-token interface, replacing deprecated NEP-21 ([official NEP list](https://near.github.io/NEPs/), [NEP-141 specification](https://github.com/near/NEPs/blob/master/neps/nep-0141.md)).

The requested MVP demo wallet deliberately does **not** use Wallet Selector, RPC, NEP-141 calls, signing or external custody. Store demo balance and ledger in the app database, mark every value as simulated, scope the session to an opaque server-issued identifier, and make trade updates atomic/idempotent. A later real provider would implement a separate interface for wallet connection, read-only account/balance, quote, user-authorized signing and transaction-status verification; it must never reuse demo balances as on-chain facts. Swaps/liquidity routing are out of scope for demo execution.

## Market-data architecture

Use adapter interfaces returning typed observations with `source`, `observed_at`, `chain`, token/pair ID, `data_kind` (`live`, `delayed`, `simulated`) and field-level availability. DexScreener documents latest profile/boost endpoints and pair/search/token endpoints with separate rate limits at its [API reference](https://docs.dexscreener.com/api/reference). These endpoints are useful for discovery and pair-level price/liquidity/volume, but do not by themselves establish source verification, holder concentration, wallet relationships, full historical candles or contract safety. Such data requires other indexers/RPC/explorers and may need credentials. Do not infer values or fill missing provider fields with zeros.

The existing project also contains EVM/Solana integrations and useful normalizers. Preserve them pending a source-level review of accuracy, rate limits, credentials and licenses. Treat HTML/token metadata, socials, LLM output and RPC-derived labels as untrusted input. Any future provider must document exact fields, chains, quota, attribution and commercial terms before being presented as live.

## Security, reliability and known limits

- No real funds, key custody, signing or real transaction execution in this rebuild.
- Demo wallet is not an authentication system. For a public deployment add proper user authentication, CSRF protection for cookie sessions, origin checks, rate limiting and per-user ownership checks before exposing private conversation data.
- Persist important events before broadcast (outbox pattern); WebSocket is transport, not the system of record. Use monotonically ordered IDs/timestamps and client deduplication/replay.
- Validate all inputs and LLM JSON output. Treat external content as untrusted data, never as authority to invoke tools or execute trades.
- CORS defaults to same-origin/explicit configured origins. Never log secrets, full authorization headers or private session tokens.
- Public market data may be delayed, incomplete or rate-limited. Holder/deployer data and verified source availability depend on chain/indexer. Current repository credentials and service accounts are not assumed to exist.
- PostgreSQL migration from existing MongoDB is a separate controlled data migration, not an implicit startup operation. Existing `.env` is excluded from inspection and must remain secret.

## Official references checked

- [React](https://react.dev/), [TypeScript](https://www.typescriptlang.org/docs/), [Vite](https://vite.dev/guide/), [Tailwind](https://tailwindcss.com/docs/installation/using-vite)
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/), [Pydantic](https://docs.pydantic.dev/latest/)
- [SQLAlchemy 2.x asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html), [Alembic](https://alembic.sqlalchemy.org/en/latest/)
- [Gemini API](https://ai.google.dev/gemini-api/docs), [OpenRouter developers](https://openrouter.ai/developers), [Cerebras docs](https://docs.cerebras.ai/)
- [NEAR Wallet Selector](https://github.com/near/wallet-selector), [NEAR standards](https://near.github.io/NEPs/), [NEP-141](https://github.com/near/NEPs/blob/master/neps/nep-0141.md)
- [DEX Screener API reference](https://docs.dexscreener.com/api/reference)

Version note: documentation is living. Exact package versions and model names will be pinned/validated when implementation dependencies are installed; this research does not invent provider quota values or guarantee third-party service availability.
