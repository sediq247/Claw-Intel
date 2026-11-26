# Zecto quick start

## War Room

1. Open War Room. The public feed is read-only.
2. Use one of the controlled evidence cases to exercise agent handoffs; fixture findings remain clearly marked simulated.
3. Open Investigations to review decisions and source records. Live observations show their provider, time and limits; missing values are not inferred.

## Private Trading Room

1. Open Settings and sign a short-lived login challenge with an injected EVM wallet (Ethereum, BNB Smart Chain, or Base) or Phantom on Solana. The login signature does not authorize a transaction.
2. Open Trading Room to access private account chats and the one-time $10,000 virtual USDC paper wallet.
3. Ask an agent to review a token or market question. Agent availability depends on server-side model configuration.
4. Open Trading Tools, choose a supported chain, enter an exact contract/mint address, and review provider source, price, observation time and limitations.
5. To record a paper order, choose buy/sell, enter the USD order value, and confirm. The server re-fetches market data and rejects stale/missing prices, overspending or overselling.
6. Review account cash, positions and recent orders in Portfolio. No blockchain order is submitted. Fees, slippage, latency and liquidity impact are not modeled.

## Settings and configuration

Settings displays configured LLM providers without returning keys, plus data source status, usage and wallet identities. Provider configuration changes are made in the server environment and require a restart.

## Watchlists, alerts and Telegram

1. Connect and verify a wallet, then open Watchlists & alerts. Add a token by exact chain and address, then create an above/below USD threshold alert.
2. Alert checks use the configured market-data provider and run at the server's configured interval. Triggered events appear in the in-app notification list; alerts are informational and never place orders.
3. For Telegram, set `TELEGRAM_BOT_TOKEN` in the private server `.env`. With `PUBLIC_BASE_URL` empty, one API instance uses long polling for local development. The connector refuses to poll when Telegram already has a webhook.
4. For a public deployment, set `PUBLIC_BASE_URL` to the public HTTPS origin and `TELEGRAM_WEBHOOK_SECRET` to a random secret of at least 32 characters. Restart to register the authenticated webhook.
5. In Settings, create a one-time link and open it in Telegram. The linking code expires after ten minutes. Keep the bot token on the server; never paste it into chat or frontend settings.
