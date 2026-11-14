# Repository audit

Initial Phase 0 audit, 2026-11-05. Inspected tracked file inventory, entrypoints, deployment files, main server/database/orchestrator code, dependency declarations, and repository status. `.env` was deliberately not read. Existing user changes are present in `Readme.MD` and untracked Python cache directories; these are preserved.

## Findings

- Current service is a custom `aiohttp` app, not FastAPI. It serves a large root `index.html`, `/frontend` static assets, a global `/ws`, and REST endpoints.
- Persistence is MongoDB through Motor/PyMongo. It stores chat, token discovery, queue, investigation, creator profile, event, market and signal records. There is no PostgreSQL or Alembic foundation.
- `server_main.py` starts `MarketEngine`; `AgentOrchestrator.start()` also creates and starts a `MarketEngine`. If both processes run, duplicate polling is possible. `Procfile` and Dockerfile call nonexistent `main.py`.
- The LLM client is process-global and uses one shared provider order/key set; it includes Grok contrary to the requested Gemini/OpenRouter/Cerebras scope. The code's September 2026 model list includes unverified/future-looking IDs and therefore needs removal or verification against provider catalogs.
- Existing agents contain meaningful business logic: multi-chain discovery, contract/token analysis, creator investigation, trade simulation, decision synthesis, debate and market polling. These should be migrated selectively, not discarded wholesale.
- Current debate is a small fixed-sequence helper with fallback prose; it is not yet the requested evidence-grounded, department-isolated deliberation engine.
- Current frontend is static HTML/JS/CSS (including inline root page) with analysis/history/markets views. It is not React/TypeScript and has a War Room-like chat view; no backend enforced trading department or demo wallet gate was found in the inspected API routes.
- Current WebSocket broadcasts and polling do not encode department/session authorization. This cannot safely carry private Trading Room content.
- No package manifest, frontend build, test directory, Alembic migration, Docker Compose, or `.env.example` is tracked.
- `.gitignore` is currently incomplete/misconfigured for generated Python caches; `.dockerignore` contents appear to contain Git/runtime ignore entries rather than a purpose-built Docker build context list.
- `Readme.MD` contains a pre-existing user edit to a table-of-contents anchor. Preserve it when rewriting the README.

## File-by-file disposition

| File | Initial status | Audit notes / migration action |
|---|---|---|
| `agents/__init__.py` | UPGRADE | Empty package marker; export only stable new interfaces when architecture settles. |
| `agents/analyzer.py` | UPGRADE | `AnalyzerAgent`, typed `AnalysisResult`, TTL cache; preserve useful contract/security checks, validate chain coverage, evidence provenance and unverified-source caveats. |
| `agents/bridge.py` | REPLACE | `NodeBridge` targets a Node `/api/publish` service not present in this repository; replace with typed internal event publishing or remove after all call sites are migrated. |
| `agents/decision.py` | UPGRADE | `DecisionAgent`, `Direction`, `SynthesisResult`; retain decision schema/logic but move final synthesis to Orion and cite persisted evidence/conflicts. |
| `agents/llm_client.py` | REPLACE | Global `LLMClient` combines credentials/priorities and Grok with rule/fallback behavior. Replace with per-department configs/adapters, explicit provider errors and usage accounting. |
| `agents/memory.py` | UPGRADE | `InvestigatorAgent` and `CreatorProfile` carry wallet/deployer investigation logic; decouple Mongo persistence and isolate memory by department/session. |
| `agents/orchestrator.py` | REPLACE | Single autonomous pipeline creates Nova, Atlas, Vega, Echo, Orion-like roles and also a second market engine. Split autonomous/trading lifecycles, eliminate duplicate startup and make tasks supervised. |
| `agents/simulator.py` | UPGRADE | `SimulatorAgent` and `SolanaSimulator` contain market/trade simulation and risk checks. Preserve analysis; isolate from trade execution and make deterministic demo ledger separate. |
| `agents/team_debate.py` | REPLACE | Fixed debate helper and fallback turn text do not meet multi-round dynamic evidence requirements; migrate useful context formatter only. |
| `agents/watcher.py` | UPGRADE | `WatcherAgent`/`TokenEvent` implement multi-chain discovery and RPC checks; preserve adapters, make observations source-labeled, configurable, rate-limited and lifecycle-safe. |
| `runtime/py_event_bus.py` | UPGRADE | In-memory synchronous bus is useful intra-process only; make typed/domain-aware and keep durable database/outbox as source of truth. |
| `runtime/server.py` | REPLACE | `ClawIntelServer` serves static UI, REST, a global unscoped WebSocket and Mongo polling; replace boundary with API routers, auth dependencies and scoped realtime events. |
| `utils/database.py` | REPLACE | Broad Mongo facade and collection/index model; map data needs to SQLAlchemy models/repositories and Alembic. Back up/export old data before any destructive transition. |
| `utils/helpers.py` | KEEP/UPGRADE | Formatting, address validation, chain labels, DEX normalizers and cache are broadly reusable; split by concern and strengthen input typing. |
| `utils/marketEngine.py` | UPGRADE | `MarketEngine` polls DexScreener and normalizes results; retain adapter logic, remove duplicate lifecycle ownership and label source/timestamp/data limits. |
| `utils/publisher.py` | UPGRADE | `EventPublisher` centralizes persistence/broadcast; retain call semantics during migration, add typed schemas/outbox, department/session authorization and replay IDs. |
| `agents_main.py` | UPGRADE | Autonomous process entrypoint with graceful stop; supervise task failures, share one DB lifecycle, document how it is run. |
| `server_main.py` | REPLACE | Initializes Mongo + aiohttp + market engine; use ASGI app lifespan and ensure a single owner for market/agent workers. |
| `index.html` | REMOVE | Legacy single-page interface; migrate useful behavior/styles, then remove after React app is active. |
| `frontend/Fstyle.css` | REMOVE | Legacy styles; document and replace through React design system. |
| `frontend/analysis.html` | REMOVE | Legacy analysis page; migrate useful fields/cards. |
| `frontend/analysis.js` | REMOVE | Legacy analysis client; migrate working API behavior then retire. |
| `frontend/app.js` | REMOVE | Legacy app client; retire when new frontend is connected. |
| `frontend/history.html` | REMOVE | Legacy history page; migrate history interaction. |
| `frontend/history.js` | REMOVE | Legacy history client; retire after records route exists. |
| `frontend/markets.html` | REMOVE | Legacy market page; useful market interactions may move to evidence/records; no separate dashboard as primary UX. |
| `frontend/markets.js` | REMOVE | Legacy market client; retire after API client migration. |
| `frontend/style.css` | REMOVE | Legacy styles; replace with accessible responsive React styling. |
| `requirements.txt` | REPLACE | Mixes current aiohttp/Mongo, unused chain SDKs, requests and providers; pin only reviewed runtime/dev dependencies after migrations. |
| `Dockerfile` | REPLACE | Copies legacy assets and starts missing `main.py`; rebuild for frontend static assets + ASGI backend and health endpoint. |
| `Procfile` | REPLACE | Starts missing `main.py`; target the actual ASGI deployment command. |
| `.dockerignore` | REPLACE | Not a correctly scoped Docker ignore file; exclude `.env`, Git, caches, node_modules, local DB/artifacts. |
| `.gitignore` | UPGRADE | Add Python/Node/build/test/local database exclusions; retain env protection. |
| `Readme.MD` | UPGRADE | Rewrite only while preserving the pre-existing user-edited anchor or its intent; provide real install/configure/run/demo instructions. |
| `.env` | INVESTIGATE | Secret-bearing local configuration, excluded from review and source control; never copy or reveal values. |
| `__pycache__/`, `agents/__pycache__/`, `utils/__pycache__/` | INVESTIGATE | Untracked generated files in working tree; leave intact during this audit and ensure ignore rules exclude them. |

## Phase 0 plan

1. Freeze the legacy implementation as reference; preserve current user edits and `.env`.
2. Add PostgreSQL schema/migrations and explicit Mongo export/migration guidance before changing runtime defaults.
3. Build typed API/event/security foundation, then port useful market/analysis behavior behind adapters.
4. Build independent department LLM config and agent orchestration; add the demo wallet ledger only after DB transactions exist.
5. Replace the static frontend after its routes/data contract are mapped; then integrate and audit deployment/security.

Since the initial audit, the legacy frontend has been retired after its behavior was mapped below. Existing MongoDB data has not been migrated or modified.

## Legacy frontend behavior mapping before retirement

| Legacy screen/scripts | Observed behavior | New implementation mapping / disposition |
|---|---|---|
| Root `index.html` + `frontend/app.js` | Main feed, agent cards, message composer, WebSocket reconnect, `/api/chat/history`, `/api/stats`, token popup/link/copy, keyboard palette. | Layout/feed and agent identities moved to React War Room; human discussion moved behind the Trading Room wallet gate. War Room composer intentionally removed. Status now calls `/health`. Token popup/command palette were not retained. Legacy WebSocket server ignored user chat except ping/pong, so the old composer was not a real agent-chat workflow. |
| `frontend/analysis.html` + `analysis.js` | User-entered token address; direct browser calls to DexScreener; staged typewriter sections named Nova, Simulator and Decision. | Replaced by evidence-backed War Room scans and repeatable labeled scenarios. Arbitrary-token analysis is not implemented. The staged UI was not preserved as a real multi-agent analysis because it was frontend-driven and not an evidence-persistent backend workflow. |
| `frontend/history.html` + `history.js` | Search/filter history backed by `/api/tokens` and `/api/investigations`, plus WebSocket updates. | Replaced by Investigations page with Orion records, evidence ledger, source/status labels and client-side search. The full old Mongo token queue/history search semantics are not migrated. |
| `frontend/markets.html` + `markets.js` | Tabs/cards/tables for market categories fetched from `/api/markets`, updated through WebSocket. | No standalone market dashboard retained, as requested. DexScreener observations now appear in the evidence ledger and War Room feed; category/gainer/loser browsing is not implemented. |
| `frontend/style.css` + `Fstyle.css` | Presentation-only layout/theme/styles. | Replaced by responsive React CSS in `frontend/src/styles.css`; old CSS files removed from the active tree. |
