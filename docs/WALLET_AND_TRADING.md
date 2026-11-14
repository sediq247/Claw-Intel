# Wallet and trading behavior

The current wallet implementation is a deterministic application database ledger. It is intentionally not a NEAR account and performs no RPC calls, wallet extension connection, signature request, key storage or transaction submission.

## Access and lifecycle

1. The browser creates a random UUID session cookie through `/api/session`; the cookie is HttpOnly, SameSite Strict and scoped to `/`.
2. `/api/wallet/connect` creates a display address beginning `demo://`, marks the session connected and seeds 1,000 demo NEAR.
3. Every Trading Room message, event, portfolio, quote and approval route uses a backend dependency that checks `wallet_connected`.
4. Disconnect clears the session wallet state and closes current private WebSockets.
5. The random cookie is sufficient for a local single-user demo, but it is not a substitute for account authentication, session revocation and CSRF controls in a public multi-user deployment.

## Quote and approval flow

- Fixture price is denominated in simulated NEAR per token. Only `demo:claw` and `demo:signal` on chain `demo` are supported.
- The quote reports amount, estimate, fee and a 30-second expiry. There is no market data source behind it.
- Rejection consumes the quote and records a rejected demo trade without changing the balance.
- Approval serializes per browser session, verifies the quote owner and expiry, checks balance including the 0.3% demo fee, consumes the quote, records an idempotent trade, deducts the demo balance and updates position quantity and average price in one database transaction.
- The execution status is `confirmed_demo`; it is not a blockchain transaction status.
- Selling, live valuation, price-impact modeling, persistent quote idempotency beyond the provided trade key, and user-configurable risk limits are not implemented.

## Future real NEAR adapter

A future adapter should be separate from `DemoWallet`, require a user-selected wallet provider, keep signing in the wallet, query the chosen network through supported RPC, check NEP-141 balance/metadata methods, fetch a real swap quote from a documented venue, request explicit user signing, and verify transaction/receipt status. That real-money scope is intentionally not enabled by this implementation.
