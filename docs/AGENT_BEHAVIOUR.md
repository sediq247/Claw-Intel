# Agent behavior

## Role prompts

- Nova reports observed market movement and data gaps.
- Atlas evaluates execution assumptions and challenges unsupported claims about liquidity.
- Vega states contract-source and static-analysis limitations; the current live market adapter has no verified contract source data.
- Echo distinguishes verified deployer/wallet links from unknowns; the current live adapter has no wallet-history source.
- Orion is asked for an independent qualified synthesis instead of a majority vote.
- Makto is limited to demo wallet and simulated portfolio operations.

Prompt inputs and external text are treated as untrusted; the model has no executable tools. War Room and Trading Room use separately named keys, models and provider order. Provider/model names must be set explicitly using current provider catalogs. Provider failures return errors or leave an observation without agent conclusions.

## Live scan

When `AUTO_SCAN_ENABLED=true` and a War Room provider key/model is configured, a lifespan-managed worker polls DexScreener latest token profiles every `AUTO_SCAN_INTERVAL_SECONDS` (300–86400; default 900). It inspects up to twelve profile entries and selects the first token with a matching base-token pair. It stores numeric market evidence, then asks Nova, Atlas, Vega and Echo for bounded perspectives, gives Atlas a challenge round and asks Orion to synthesize. There are no fabricated values when fields are missing.

Live scan boundaries: one observation per cycle, no persisted investigation aggregate linking all findings beyond evidence IDs in messages/events, no separate durable agent memories, and no contract/deployer/holder indexer integrations. The worker does not start agent analysis when no War Room provider is configured.

## Deterministic scenarios

The two demo cases write authored scenario text labeled `[SIMULATED SCENARIO: ...]`. They demonstrate roles, evidence references, persistence and event broadcast without pretending to be LLM output or live intelligence.

## Current isolation limits

Trading conversation and events are session-scoped. War Room is public. There is no multi-user identity/authentication system, durable per-agent memory, debate revision record, or per-department token-cost ledger yet.
