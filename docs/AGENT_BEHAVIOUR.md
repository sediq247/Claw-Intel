# Agent behavior

## Role prompts

- Nova reports observed market movement and data gaps.
- Atlas evaluates execution assumptions and challenges unsupported claims about liquidity.
- Vega states contract-source and static-analysis limitations; the current live market adapter has no verified contract source data.
- Echo distinguishes verified deployer/wallet links from unknowns; the current live adapter has no wallet-history source.
- Orion is asked for an independent qualified synthesis instead of a majority vote.
- Makto receives the authenticated user's virtual USDC balance and positions as context. It cannot alter the ledger; an order requires explicit user confirmation in the paper-order panel.

Prompt inputs and external text are treated as untrusted; the model has no executable tools. War Room and Trading Room use separately named keys, models and provider order. Provider/model names must be set explicitly using current provider catalogs. Provider failures return errors or leave an observation without agent conclusions.

## Live scan

When `AUTO_SCAN_ENABLED=true` and a War Room provider key/model is configured, a lifespan-managed worker polls documented DexScreener attention feeds every `AUTO_SCAN_INTERVAL_SECONDS` (300–86400; default 900). Candidates need recent transactions, nonzero recent volume, and liquidity; paid boosts and profile placement are excluded from the attention score. Nova chooses one exact candidate from that measured set before the LangGraph investigation job is queued. The investigation stores provider evidence, collects bounded perspectives, runs configurable cross-examination (four challenges by default), and asks Orion to synthesize. If Nova cannot choose a valid candidate or the provider is unavailable, the cycle queues no investigation. Missing facts remain unavailable rather than being filled with fabricated values.

Live scan boundaries: one observation per cycle, and no contract/deployer/holder indexer integrations. The worker does not start agent analysis when no War Room provider is configured. Investigation records link findings to evidence; Trading Room agent memory is bounded and scoped by private chat, including across session rotation.

The autonomous War Room schedule is stored in PostgreSQL and uses a PostgreSQL advisory lock so only one application replica owns the scan/news scheduler. Work sessions last 2–3 hours; at the work deadline, the system stops claiming cases, drains existing investigations, then pauses for 30–35 minutes. During work, a separate ambient conversation may use GDELT DOC ArticleList results, but only HTTPS links from a fixed publisher allowlist are passed to agents. Agents receive the headline, date, publisher, and URL, not article text; they must distinguish the headline from confirmed facts and avoid repeating allegations or gossip about private people. Source links are rendered with the messages. The [official GDELT DOC 2.0 API description](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) documents ArticleList and JSON article results.

## Deterministic scenarios

The two controlled cases write authored scenario text labeled `[SIMULATED SCENARIO: ...]`. They exercise roles, evidence references, persistence and event broadcast without presenting fixture output as live intelligence.

## Current isolation limits

Trading chats and investigations are owned by verified user IDs. Trading events remain scoped to the current browser session. War Room is public. Account identity uses EVM/Solana message signatures; Telegram, other wallet families, and live multi-worker event delivery remain unsupported. Agent memory is chat-scoped; provider-reported costs are tracked when available, but estimated cost is never substituted.
