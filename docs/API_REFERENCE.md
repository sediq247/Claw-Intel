# API reference (implemented surface)

All JSON endpoints are same-origin by default. Browser requests carry an HttpOnly `claw_session` cookie created by `POST /api/session`; set `ALLOWED_ORIGINS` for development origins. A cookie is a local demo session, not a user login.

## Health and public department

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/health` | Public | PostgreSQL connectivity and boolean provider readiness; never returns keys. |
| POST | `/api/session` | Public | Creates or resumes the browser demo session and sets the HttpOnly, SameSite=Strict cookie. |
| GET | `/api/agents` | Public | Returns the six role descriptions. |
| GET | `/api/settings/status` | Public | Returns provider readiness and configured model names, without credentials. |
| GET | `/api/autonomous/messages?limit=100` | Public | Read-only autonomous message feed. There is intentionally no POST route. |
| GET | `/api/autonomous/evidence` | Public | Evidence records with source, observation time, status, fields and limitations. |
| GET | `/api/autonomous/events?after=0` | Public | Ordered persisted event replay for the public War Room channel. |
| GET | `/ws/autonomous?after=0` | Public | War Room real-time feed; accepts only ping messages. |

## Wallet-gated Trading Room

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/wallet` | Browser session | Demo wallet connection state and simulated balance. |
| POST | `/api/wallet/connect` | Browser session | Creates a simulated `demo://` address and initial test balance. |
| POST | `/api/wallet/disconnect` | Browser session | Disconnects wallet and closes private WebSockets. |
| GET | `/api/trading/messages` | Connected demo wallet | Reads this session's private conversation. |
| POST | `/api/trading/messages` | Connected demo wallet | Body: `{"content":"@vega ..."}`. Routes a mention to that agent or defaults to Orion. Provider failure returns 503 and does not fabricate a reply. |
| GET | `/api/trading/events?after=0` | Connected demo wallet | Ordered event replay scoped to this browser session. |
| GET | `/api/trading/portfolio` | Connected demo wallet | Simulated balances, positions and recent trades. |
| POST | `/api/trading/quotes` | Connected demo wallet | Body contains chain, fixture token, buy side and positive NEAR amount. Only `demo:claw` and `demo:signal` on chain `demo` are quotable. Quote expires after 30 seconds. |
| POST | `/api/trading/approve` | Connected demo wallet | Body contains quote UUID, idempotency key and explicit approval boolean. Approved quote updates the simulated ledger atomically. |
| GET | `/ws/trading?after=0` | Connected demo wallet | Session-scoped private feed; rejects missing/disconnected sessions and disconnect closes active subscribers. |

## Deterministic scenarios

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/scenarios` | Lists explicitly simulated scenarios. |
| POST | `/api/scenarios/suspicious-token/run` | Stores a controlled evidence fixture and five simulated role findings. |
| POST | `/api/scenarios/potential-opportunity/run` | Stores an opportunity fixture with explicit unknowns and limitations. |

Errors return standard FastAPI JSON `{"detail":"..."}`. No endpoint accepts a private key, signs transactions or calls a blockchain.
