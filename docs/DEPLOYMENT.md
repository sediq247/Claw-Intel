# Deployment and operations

## Local Docker Compose

1. Copy `.env.example` to `.env` and set a non-default `POSTGRES_PASSWORD` plus the provider keys/models you want to use. Choose model IDs from the providers' current official catalogs.
2. Run `docker compose up --build` from the repository root.
3. Compose waits for PostgreSQL, builds the Vite app, applies Alembic migrations, then starts Uvicorn on internal port 8000 and publishes it on host port 6548 by default.
4. Open `http://localhost:6548/health` and the web app at `http://localhost:6548`.

The default Compose password is for a local disposable environment only. Set `COOKIE_SECURE=true` behind HTTPS. Set `ALLOWED_ORIGINS` to exact trusted origins; do not use `*` with credentials.

## Direct development

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
alembic upgrade head
uvicorn backend.app.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

## Operations

- Migrate: `alembic upgrade head`.
- Check schema revision: `alembic current`.
- Health: `GET /health`.
- Automatic scan cadence: `AUTO_SCAN_INTERVAL_SECONDS`; turn off with `AUTO_SCAN_ENABLED=false`.
- Optional external War Room agents: set `WARROOM_A2A_AGENT_CARDS` to a comma-separated list of trusted public HTTPS Agent Card URLs. The integration is disabled by default. Never add private/internal endpoints; A2A replies are untrusted input and cannot access the Trading Room.
- Optional stock-history feed: set `ALPHA_VANTAGE_API_KEY`. Zecto keeps normalized daily OHLCV observations transiently in process memory and enforces a shared atomic daily provider budget (`ALPHA_VANTAGE_DAILY_CALL_BUDGET`, default 20) across app replicas. Set a budget within your provider plan's current quota. The endpoint does not provide real-time execution prices.
- PostgreSQL data lives in the named Compose volume `clawintel_postgres` for migration compatibility. Migration `0027_clear_existing_data` clears its application rows at startup.
- Back up PostgreSQL before any destructive action or schema migration. The legacy Mongo database is neither read nor deleted by this service.

## Release validation limits

The checked-in runtime startup command is now the ASGI module, replacing the former nonexistent `main.py`. Unit tests, Vite production builds, and Alembic offline SQL generation can be validated locally. A working Docker daemon and PostgreSQL server are required to verify container build/startup, live migration, database integrity, and full deployment health. Live A2A interoperability also requires a trusted external Agent Card endpoint; no partner endpoint is supplied by this repository.
