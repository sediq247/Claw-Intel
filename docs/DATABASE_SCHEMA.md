# Database schema

PostgreSQL is the active application's only database. `backend/app/models.py` defines SQLAlchemy 2.x mappings. `backend/app/migrations/versions/0001_initial.py` creates the first Alembic revision. The API intentionally does not create or mutate schema at startup.

| Table | Purpose | Isolation / constraints |
|---|---|---|
| `browser_sessions` | Opaque browser-local demo session and wallet gate | UUID key; session cookie is HttpOnly and SameSite Strict. This is not multi-user authentication. |
| `conversation_messages` | War Room and Trading Room messages | Department and session are stored; trading rows are queried only with the owning session ID. |
| `evidence` | Market observation and scenario evidence | Source, chain, token, observation time, live/delayed/simulated kind, provider fields and limitations are retained. |
| `durable_events` | Ordered department and session event history | Sequence key, unique event UUID and department/session index; committed before WebSocket broadcast. |
| `demo_wallets` | Simulated NEAR balance | One wallet per session, decimal balance; never a real account. |
| `demo_quotes` | Expiring demo quote and one-time consumption | Owner session and expiry checked when approving; no real price service. |
| `demo_trades` | Simulated approved/rejected trades | Per-session unique idempotency key. |
| `demo_positions` | Simulated token positions | Unique session + chain + token. |

## Migration commands

```powershell
alembic upgrade head
alembic current
alembic history
```

Take backups before migrations in any existing deployment. MongoDB data from the former application is not imported or deleted by this revision. A production Mongo-to-PostgreSQL migration utility is not yet implemented.

## Local reset

For a disposable local compose environment only, stop the app and remove the named `clawintel_postgres` volume with an explicit review of the target volume. This destroys local demo data. There is no in-app reset endpoint and no production-safe reset command yet.
