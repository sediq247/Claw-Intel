# War Room session scheduler

The PostgreSQL `autonomous_schedule` row is derived from UTC wall time. The scheduler is single-leader per database using a PostgreSQL advisory lock. On startup and after each block boundary, it recomputes the current block; finishing work early or restarting the service does not move the next boundary.

| UTC minute | Phase | Behavior |
|---|---|---|
| 00–14 | `crypto` | Crypto discovery and ambient War Room discussion may run when configured. |
| 15–29 | `resting` | Crypto investigation job claims are paused; the room shows a scheduled rest. |
| 30–44 | `stocks` | Configured stock symbols are loaded from shared daily OHLCV observations; Nova, Atlas, Vega, and Orion discuss only supplied evidence. Crypto jobs remain queued. |
| 45–59 | `idle` | No autonomous market session; crypto jobs remain queued for the next crypto block. |

Phase start and end timestamps are persisted as UTC-aware datetimes. Migration `0022_hourly_market_phases` converts an existing legacy schedule row to the phase and bounds active at migration time before enforcing the four-value check constraint. Migration `0023_a2a_reception_queue` stores guest requests and admission state. Downgrade of migration 0022 maps phases unsupported by the former schema to `resting`.

Migration `0024_remove_persisted_evidence` deletes previously retained provider evidence and forecast snapshots; `0025_stock_cache` removes daily stock-bar storage; `0026_no_a2a_response` removes stored external guest replies. The scheduler passes current market observations to agents in memory and queues only a chain/address locator; a worker fetches a fresh observation before analysis. These migrations have not been applied to the unavailable local PostgreSQL service, so this describes intended post-migration retention behavior, not verified live database state.

The phase helper has deterministic boundary/timezone tests; the job worker rejects claims outside `crypto`, and the active crypto scan, agent job, ambient discussion, A2A task, and stock debate are bounded by the persisted block deadline. Timed-out investigation jobs are retried in a later crypto block. Stock data is daily historical OHLCV, never intraday market pricing. Alpha Vantage remains disabled until the operator selects an applicable terms status and configures a key. Live PostgreSQL boundary behavior, multi-replica concurrency, and real provider calls have not been performed.
