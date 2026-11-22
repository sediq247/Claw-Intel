# Wallet identity and paper trading

## Wallet authentication

The application supports EIP-191 signatures from EVM wallets on Ethereum, BNB Smart Chain, and Base, plus Solana Ed25519 message signatures through Phantom. The Trading Room, top bar, and Settings open the same wallet chooser without navigating away. Phantom is the featured first choice. EVM account selection and signing use Wagmi and Viem, with MetaMask, Coinbase Wallet, EIP-6963/injected browser wallets, and optional WalletConnect connectors. WalletConnect requires a public Reown project ID: set `VITE_WALLETCONNECT_PROJECT_ID` in `.env` before the frontend build (for Docker Compose, set it in the project `.env`; it is passed as a Docker build argument). The project ID identifies the dapp and is not a wallet secret.

The server creates five-minute, single-use challenges bound to the configured Origin, chain, and address; signature verification stores the wallet identity and rotates the session cookie. EVM messages use the SIWE field layout, checksum addresses, and an alphanumeric nonce; generic injected connectors are accepted as `Browser wallet`. Production settings reject startup unless `COOKIE_SECURE=true`. No private keys, seed phrases, token approvals, or chain transactions are requested. The signature prompt authenticates the account only. Phantom uses its injected Solana provider and raw `signMessage` challenge for broad compatibility; SIWS `signIn` and off-chain-message v1 support are not implemented. WalletConnect, Trust Wallet, Solflare, Backpack, and mobile/extension flows require real-device verification before they can be called tested. EVM contract-wallet verification via ERC-1271 is also not implemented. HOT/Meteor require a separate NEAR adapter and are not implemented.

### Wallet UI research and implementation choice

The official [Wagmi connect-wallet guide](https://wagmi.sh/react/guides/connect-wallet) documents both a custom connector chooser and third-party UI libraries built on Wagmi. [RainbowKit](https://rainbowkit.com/docs/introduction) is one established customizable Wagmi/Viem UI option; [Viem's `signMessage`](https://viem.sh/docs/actions/wallet/signMessage) action uses EIP-191 message signing. ClawIntel uses Wagmi connectors with a product-matched in-app chooser so Phantom can be the primary Solana option while EVM connectors share the same backend challenge-verification flow. WalletConnect's Wagmi connector needs a Reown project ID, so it stays an explicit optional build-time integration rather than showing a nonfunctional connect action.

The supported chain identity list and market-data coverage are separate. Wallet authentication does not mean market observations, RPC analysis, executable quotes, or trading are available on every network.

## Account ownership and session lifecycle

- `users` is the owner key. Each verified `(chain,address)` maps to exactly one user.
- A new identity session gets a fresh opaque HttpOnly cookie. The server stores a user ID on that session, and every Trading Room endpoint checks it.
- Trading chats are owned by user ID, so browser session rotation does not hide a user's prior private chats. Messages are read only after the server confirms chat ownership.
- Account data is removed from the browser query cache after logout. Logging out rotates to a new anonymous session.
- When an authenticated user signs a second wallet, that address is linked to the same account. A wallet already owned by another user cannot be linked.

## Paper account

Each verified user has one `paper_accounts` row. The first portfolio read creates the initial $10,000 virtual USDC balance; the unique user constraint prevents reseeding on later sessions. Paper orders are entered in USD, use fresh exact-address token/USD observations, and debit or credit virtual USDC directly. The resulting order, position, and balance update is written in a single database transaction. The account is locked while validating and applying an order; an idempotency key cannot apply a fill twice, and reusing it for a different order returns a conflict.

Prices must be positive and no more than five minutes old. Only exact EVM contract addresses and Solana mint addresses on Ethereum, BNB Smart Chain, Base, or Solana are accepted. Ticker-only orders, stale or missing prices, unsupported chain/address pairs, overspending, and overselling are rejected. The user must explicitly confirm the order in the frontend; chat text alone can never alter the ledger.

Fills are virtual and use the last provider-reported price. Fees, slippage, latency, liquidity impact, market impact, and tax are not modeled. Position valuation is withheld until a fresh provider mark is available. No route submits or signs a blockchain transaction. Real execution requires a separate, audited quote and signing integration and is outside this implementation.

### Internal virtual-USDC transfers

Dashboard Send and Receive are limited to internal transfers between initialized ClawIntel paper accounts whose recipient has a verified wallet identity on the selected network. Transfers lock both accounts in stable order, debit and credit in one PostgreSQL transaction, and are idempotent per sender. The Receive address is an identity lookup hint only; it is not an on-chain deposit address. External deposits and blockchain transfers are unsupported.

Legacy `demo_wallets`, `demo_quotes`, `demo_trades`, and `demo_positions` tables remain for reversible schema compatibility. Their write APIs return `410 Gone`; the live product does not read them.

## Agent capability boundaries

Nova, Atlas, Vega, Echo, Makto, and Orion operate on bounded, sanitized evidence records and persistent per-chat memory. Agents are instructed to name evidence sources and observation times, separate observations from interpretation, identify missing facts, and avoid fabricating contract, holder, deployer, or execution claims. The agent workspace is isolated per call, size-limited, temporary, and has no shell or code execution. Makto receives the authenticated account's virtual cash and positions as context, but can never execute an order; the user must confirm an order in the UI.

Automated agent answers remain probabilistic. Provider/model quality, real wallet extension prompts, cross-device flows, and transaction execution are not covered by this paper trading feature.
