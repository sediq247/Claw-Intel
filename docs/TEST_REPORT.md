# Test report — 2026-11-17

No project `.env` values were printed. External provider and database dependencies are mocked in backend contract tests; no live provider request or database transaction succeeded during this validation.

## Commands and results

| Check | Result |
|---|---|
| `python -m compileall -q backend agents runtime utils server_main.py agents_main.py` | PASS. |
| `python -m pytest -q -o cache_dir=work\pytest-cache` | PASS: 38 tests, including Alembic revision ID length. |
| `npm run build` (in `frontend/`) | PASS: TypeScript and Vite production bundle; 3,750 modules transformed, largest split bundle 435.98 KB (gzip 140.25 KB). |
| `alembic upgrade head --sql` | PASS: offline SQL generated through `0010_investigation_owner`; does not apply to a server. |
| `git diff --check` | PASS; Git emitted line-ending notices only. |
| Mocked provider/orchestration | PASS: exact address, source/time/limitations, bounded evidence, agent roles/debate, wallet signature verification, and unavailable providers are covered. |
| Paper order contract | PASS: mocked fresh provider observation is applied to user-owned USD cash and position with explicit virtual-fill assumptions. |
| Live PostgreSQL, Docker, providers and browser devices | NOT RUN: Docker daemon access is denied from this shell; provider credentials not exercised, and browser automation did not reach the project page. User-provided logs show PostgreSQL healthy; migration retry is pending with the shortened revision IDs. |

## Coverage boundaries

The tests do not prove live PostgreSQL migration behavior, account row-lock concurrency, cross-user isolation under load, rollback/restore, frontend browser accessibility, wallet extension behavior, Telegram delivery, or deployment operations. The user-requested database wipe was not performed because there is no verified live database connection; a custom-format dump file is present, but only its archive header was checked.
