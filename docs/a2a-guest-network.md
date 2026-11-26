# A2A guest network status

## Implemented

- War Room-only A2A client using operator-configured Agent Card URLs (`WARROOM_A2A_AGENT_CARDS`).
- HTTPS-only endpoints on the default port, public-address validation, redirect refusal, bounded response sizes/timeouts, same-origin endpoint checks, and JSON-RPC response validation.
- Agent Cards must declare A2A protocol 1.x and a same-origin HTTPS task endpoint. Bounded skill claims are recorded for attribution; they are not treated as identity proof.
- A PostgreSQL-backed reception queue records validated requests, screening results, trust state, arrival order, admission, outcome, and expiry. The independent worker admits the first two queued eligible guests per active 15-minute market block, with at most seven waiting requests. PostgreSQL row/advisory locks protect concurrent workers.
- The browser can select only a currently available configured agent. Requests include a bounded public-research question and never include wallet, portfolio, or Trading Room context.
- Guest responses are bounded, marked untrusted, and stored in attributed War Room events and the reception record. They are shown in the A2A reception panel, not placed in native agent memory or fed back to the LLM as trusted dialogue.
- Requests can be withdrawn by their submitting browser session while still queued. Requests that expire with the market block or return after its deadline are rejected. Worker timeout/restart is recorded; it does not dispatch the same guest twice.

## Not implemented

The reception worker is independent of Nova's model reasoning, but a discovered endpoint is not an authenticated guest identity. The operator configuration is the approval boundary; invitations and external-originated connection requests are not supported. Nova does not yet have a dedicated model-visible `check_reception` operation or automatic spoken introduction. The UI and event stream attribute external contributions, and native agents do not receive raw guest responses as dialogue.

## Operational limit

DNS is resolved and checked before the HTTP client makes its request, but the client does not pin the resolved address for the connection. Network-level egress filtering is not implemented here. Production use needs a vetted partner allowlist and external egress controls; this application-level validation alone is not a complete SSRF defense.
