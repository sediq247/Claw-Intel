# API reference (implemented surface)

All JSON endpoints are same-origin by default. Browser requests carry an HttpOnly `claw_session` cookie created by `POST /api/session`; set `ALLOWED_ORIGINS` for development origins. The cookie identifies a browser session; signed wallet authentication is required for private Trading Room and paper portfolio data.

## Health and public department

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/health` | Public | PostgreSQL connectivity and boolean provider readiness; never returns keys. |
| POST | `/api/session` | Public | Creates or resumes an anonymous browser session and sets the HttpOnly, SameSite=Strict cookie. |
| GET | `/api/agents` | Public | Returns the six role descriptions. |
| GET | `/api/settings/status` | Public | Returns provider readiness and configured model names, without credentials. |
| GET | `/api/autonomous/messages?limit=100` | Public | Read-only autonomous message feed. There is intentionally no POST route. |
| GET | `/api/autonomous/forecasts?limit=30` | Public | Latest immutable forecast versions with the exact source snapshot and supporting evidence references. |
| GET | `/api/autonomous/forecasts/{id}/history` | Public | Prior versions for the selected asset; old forecasts are not overwritten. |
| GET | `/api/autonomous/events?after=0` | Public | Ordered persisted event replay for the public War Room channel. |
| GET | `/ws/autonomous?after=0` | Public | War Room real-time feed; accepts only ping messages. |
| GET | `/api/autonomous/a2a/agents` | Verified wallet account | Discovers only operator-configured HTTPS Agent Cards. |
| POST | `/api/autonomous/a2a/delegate` | Verified wallet account | Delegates a bounded public-research question to one discovered agent. No private wallet, portfolio, or Trading Room context is sent; responses are untrusted and logged as War Room events. |
| GET | `/api/market/stocks/{symbol}/daily` | Verified wallet account | Returns cached, normalized Alpha Vantage daily OHLCV for a validated ticker. Historical daily data only, not an executable or real-time quote. |

## Wallet-authenticated Trading Room and paper ledger

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/trading/chats` | Verified wallet account | Lists private chats owned by the authenticated account, across browser session rotation. |
| POST | `/api/trading/chats` | Verified wallet account | Creates a private conversation. |
| GET | `/api/trading/messages?chat_id=...` | Chat owner | Reads messages only when the chat belongs to the verified account. |
| POST | `/api/trading/messages` | Verified wallet account | Body: `{"content":"@vega ...","chat_id":"..."}`. Routes a mention to that agent or defaults to Nova. Provider failure does not fabricate an agent reply. |
| GET | `/api/trading/token-search?chain=...&address=...` | Verified wallet account | Resolves exact token address, source, timestamp and limitations. Symbols are rejected. |
| GET | `/api/paper/portfolio` | Verified wallet account | Creates the account’s one-time $10,000 virtual USDC allocation if needed; returns the USDC balance, live-marked positions, and recent paper orders. |
| POST | `/api/paper/orders` | Verified wallet account | Requires supported chain/address, buy or sell, $1–$10,000 order value, and an idempotency key. Re-fetches exact-address token-price evidence, rejects missing/stale prices, locks the account row, and updates USDC balance, position, and order in one transaction. |
| GET | `/api/trading/events?after=0` | Verified wallet account | Ordered event replay scoped to the current authenticated browser session. |
| GET | `/ws/trading?after=0` | Verified wallet account | Private real-time feed; rejects sessions without an authenticated user. |

Legacy `/api/wallet`, `/api/trading/portfolio`, `/api/trading/quotes`, `/api/trading/approve`, and `/api/trading/scenarios/market-shift` paths return `410 Gone`. They cannot write fixture trades or create another ledger. The current paper fill uses the latest provider-reported USD price; fees, slippage, latency, and liquidity impact are not modeled.

## Deterministic scenarios

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/scenarios` | Lists explicitly simulated scenarios. |
| POST | `/api/scenarios/suspicious-token/run` | Stores a controlled evidence fixture and five simulated role findings. |
| POST | `/api/scenarios/potential-opportunity/run` | Stores an opportunity fixture with explicit unknowns and limitations. |

Errors return standard FastAPI JSON `{"detail":"..."}`. No endpoint accepts a private key, signs transactions or calls a blockchain.

## Wallet identity endpoints

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/api/auth/wallet/challenge` | Browser session + configured Origin | Create a five-minute single-use EVM/Solana sign-in challenge for an allowed wallet and validated address. |
| POST | `/api/auth/wallet/verify` | Same browser session + configured Origin | Verify EIP-191/EIP-4361-shaped EVM signature or Solana Ed25519 signature; create/login/link wallet identity and rotate to a fresh session on login. |
| GET | `/api/auth/me` | Browser session | Return authenticated identity state and verified wallet addresses. |
| POST | `/api/auth/logout` | Browser session | Clear identity and rotate to an anonymous session. |

Wallet authentication proves address control only. It does not enable real-chain order execution. The verified user ID owns the paper account and Trading Room chats; account data is isolated by user. See `docs/WALLET_AND_TRADING.md` for supported interfaces and untested paths.
