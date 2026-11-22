# Security review

This is a code-path review, not a third-party security audit or production approval. Current findings are summarized in [`docs/audits/02-security-multitenancy-audit.md`](audits/02-security-multitenancy-audit.md).

| Area | Status | Evidence / remaining work |
|---|---|---|
| Wallet identity | Implemented for EVM EOA and Phantom Solana | Single-use, short-lived, Origin-bound challenges; EVM nonce follows SIWE's alphanumeric rule; generic injected connectors are accepted. Phantom currently uses raw message signing, not SIWS. ERC-1271 contract accounts and real extension/database-backed login validation remain outstanding. |
| Account ownership | Implemented in application queries/schema | User IDs own wallet identities, chats, investigations, paper accounts, positions and orders. PostgreSQL row-level security and live adversarial multi-user testing are not present. |
| Paper order integrity | Implemented; live DB behavior unverified | Exact-address fresh provider data, positive price/precision checks, explicit UI confirmation, cash/position checks, row lock, atomic persistence and idempotency are covered by mocked tests. |
| Real funds and keys | No real-money execution path | No private key storage, seed collection, signing request, swap route or blockchain transaction is submitted. Paper fills are virtual and omit market frictions. |
| War Room | Public and read-only | No public feed composer; public scans/scenario endpoints have no production rate limiting yet. |
| Cookies and origins | Partial | HttpOnly/SameSite Strict, explicit CORS origins and Origin checks; production settings now reject `COOKIE_SECURE=false`. Rate limits, full CSRF policy, proxy trust and session-revocation tests need review. |
| WebSockets | Partial | Trading connection validates the authenticated user session; hub is process-local and events are session-scoped, so multi-worker fanout and revocation are open. |
| Prompt/evidence boundaries | Partial | External data and attachments are untrusted; agent tools are disabled and scratch workspaces bounded. Output schema/moderation controls are limited. |
| DB recovery | Not verified | The database connection is unavailable and no reset/live migration was performed. A custom-format dump file exists, but its full restore validity was not checked. |
| Operations | Not ready | No global rate limiting, full audit telemetry, load testing, or live deployment validation. |

Before public launch, complete PostgreSQL integration/concurrency/restore tests, rate limits, structured redacted telemetry, multi-worker event delivery, browser accessibility checks, real wallet/provider tests, and the remaining product integrations in Audit 3.
