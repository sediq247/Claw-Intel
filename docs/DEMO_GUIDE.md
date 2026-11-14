# Demo walkthrough

## War Room

1. Open the application and select War Room. It has no human composer.
2. From the scenario panel, run Suspicious Token or Potential Opportunity. The messages carry a simulated badge and use authored deterministic text.
3. Open Investigations to read Orion decisions and the evidence ledger. A live observation (when configured) shows DexScreener source, fetch time and limits. Missing values remain unavailable.

## Trading Room

1. Select Trading Room and connect the demo wallet.
2. Confirm the page now shows a private conversation and simulated balance.
3. Ask an agent a question or use a mention chip such as `@vega`. A provider must be configured; otherwise the app reports an explicit provider error.
4. To prepare a deterministic demo quote, select CLAW or SIGNAL, enter a NEAR amount and choose Get Simulated Quote.
5. Review quote expiry, fixture price and fee, then approve or reject. The portfolio changes only after approval and remains labeled simulated.
6. Disconnect the demo wallet and confirm that the room closes and private endpoints return a gate error.

## Settings

Settings shows configured LLM providers without returning their keys. Use the scenario controls to repeat the deterministic War Room cases. Provider configuration changes are made through server environment variables and restart; there is no settings mutation API.
