# Test report — 2026-11-08

No project `.env` values were printed. The backend was run using an isolated Python 3.12 runtime and dependency set. Provider/network integrations below use mocks; no authenticated live provider request was made.

## Commands and results

| Check | Result |
|---|---|
| `python -m compileall -q backend tests server_main.py agents_main.py` | PASS. |
| `python -m pytest -c pytest.ini -q` | PASS: 15 tests; one Starlette `TestClient`/httpx deprecation warning. |
| `alembic upgrade head --sql` | PASS: offline SQL includes initial schema and `0002_agent_workflows`. This does not apply migrations to a server. |
| `npm run build` | PASS: TypeScript compilation and Vite production bundle; 1,637 modules. |
| Mocked DexScreener/CoinGecko/EVM RPC | PASS: provider metrics retain numeric values, key is sent in a header, exact token base contract is selected, bytecode is not persisted, unavailable values remain explicit. |
| Mocked orchestration | PASS: independent initial agent prompts, evidence filtering, persistent findings/usage, dynamic cross-examination, rebuttal and Orion decision. |
| Docker build / live PostgreSQL / browser E2E / authenticated provider calls | NOT RUN: no Docker daemon or PostgreSQL service was available; external provider credentials were not exercised. |

## Focused test coverage

1. War Room does not expose a human-message route or composer.
2. Compatibility entrypoints use the active ASGI launcher.
3. Department-scoped provider keys/models and model-list fallback.
4. Missing providers produce explicit failures instead of fabricated completions.
5. DexScreener fields and limitations are retained; numeric parsing works and missing values remain missing.
6. User-submitted token lookup matches the exact base contract.
7. Independent investigation, filtered evidence, dynamic challenge, persisted usage/findings, and final Orion result.
8. CoinGecko header authentication and market parsing.
9. EVM RPC exposes metadata without raw bytecode.
10. Trading API and WebSocket reject sessions without a connected demo wallet.
11. WebSocket events remain scoped by department and Trading Room session.
12. Durable event commits precede broadcast.

These focused checks do not prove external provider availability or replace PostgreSQL integration, browser automation, trade concurrency, rollback, live migrations, and end-to-end acceptance for every master-prompt scenario.
