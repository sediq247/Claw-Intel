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
- PostgreSQL data lives in the named Compose volume `clawintel_postgres`.
- Back up PostgreSQL before any destructive action or schema migration. The legacy Mongo database is neither read nor deleted by this service.

## Release validation limits

The checked-in runtime startup command is now the ASGI module, replacing the former nonexistent `main.py`. The Vite production build and initial Alembic offline SQL generation have been validated. This environment has no running Docker daemon or PostgreSQL server, so container build/startup, live migration, database integrity, and full deployment health remain unverified.
