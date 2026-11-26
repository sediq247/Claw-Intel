# Data providers and capability status

Provider names below describe the current repository state. Candidate integrations are not enabled unless specifically marked as implemented. Keys remain server-side.

## Active and optional sources

| Provider | Capability | State | Access/cost | Terms and limitations |
|---|---|---|---|---|
| DexScreener | DEX discovery, pair snapshots, price/volume/liquidity observations | Implemented; public endpoints | No key configured in this repository | Public API availability/quotas apply. Snapshot fields are not executable quotes or proof of safety. |
| CoinGecko | Contract lookup and market-cap/ATH enrichment | Optional adapter | API key optional; paid plan not enabled by default | Enrichment is limited to supported listed contracts; no claim that every asset is covered. |
| Ethereum, BNB Chain, Base, Solana RPC | Public chain metadata and contract/account observations | Optional RPC adapters, one configured endpoint per chain | Operator-supplied URLs; public endpoints have no SLA | No wallet history indexer or entity attribution provider is connected. RPC checks do not certify a contract. |
| Alpha Vantage | Daily equity OHLCV | Implemented for authenticated history and the autonomous stock phase | API key, shared daily call budget, and `ALPHA_VANTAGE_LICENSE_STATUS` required | This adapter is daily historical data, not a real-time quote. Official documentation describes 25 free API requests/day; commercial access/data use requires the relevant authorized arrangement. Current implementation defaults to `disabled`. |
| Exa | Public web search | Optional War Room endpoint | Server key and persistent daily request budget | Returned snippets are untrusted evidence; verify claims against source pages. |
| GDELT DOC | Headline discovery for ambient War Room discussion | Public endpoint with publisher allowlist | No key; bounded request cadence | Only headline, date, publisher, and source URL are passed. It is not treated as article-body verification. |
| RugCheck analytics | Indexed-platform reported rug count over seven days | Dashboard summary only | Public endpoint; cached | This is not a rolling 60-minute event feed. Per-event classification and coverage are not implemented. |
| Gemini, OpenRouter, Cerebras | LLM reasoning | Optional, department-scoped | Operator API keys and model IDs; cost varies by model/provider | Only configured providers are called. Provider-reported cost is recorded when returned; unknown prices are not estimated. |

For Alpha Vantage, consult the [official API documentation](https://www.alphavantage.co/documentation/), [support/usage limits](https://www.alphavantage.co/support/api-key/), and [terms of service](https://www.alphavantage.co/terms_of_service/) before enabling a deployment. The setting is an operator declaration, not an automated legal determination.

## Capability analysis

The central registry in `backend/app/tool_registry.py` currently brokers twelve deterministic analyses over evidence already retrieved by the application. It does not call independent sources for derivatives, social sentiment, fundamentals, holder distribution, or macroeconomic series. Those capability outputs explicitly list missing inputs. Provider status distinguishes basic key/URL configuration in the Settings API, but full connected/operational/live-verified health probes and terms state for every source are not yet implemented.

## Deferred candidates

These are examples from the upgrade prompt, not integrations. They remain deferred until a task, source coverage, terms, operational budget, and security fit are justified:

| Candidate category | Example candidates | State / reason |
|---|---|---|
| Chain explorer and indexed wallet history | Etherscan-compatible APIs, Blockscout, Solscan | Not integrated; no reliable multi-chain wallet-history or entity attribution contract is configured. |
| DEX analytics and token discovery | GeckoTerminal and additional DEX indexers | Deferred; current DexScreener adapter is the existing discovery source. |
| Quote, route, simulation | Jupiter, Tenderly | Not integrated; live swaps/signing are outside the research path and require separate simulation, transaction review, and user confirmation. |
| Derivatives and protocol data | Funding/open-interest, DeFiLlama-like datasets | Not integrated; no source with configured license, freshness, and normalized evidence schema. |
| Social/narrative monitoring | Social network APIs and licensed feeds | Deferred until lawful access, data retention, and redistribution terms are reviewed. |
| Browser/code sandbox and injection defenses | Isolated retrieval workers, gVisor/Firecracker, external classifiers | Not integrated as an OS/network boundary. Prompt text and deterministic tool permissions are not a substitute for egress and process isolation. |

No candidate is automatically used as a fallback. Adding a provider requires an adapter, schema and provenance checks, budget policy, terms review, failure behavior, and deterministic tests.
