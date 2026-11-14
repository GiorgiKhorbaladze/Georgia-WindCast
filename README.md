# Georgia WindCast

Private project for monitoring Georgia's aggregate wind generation and site-level model wind. See the [technical specification and roadmap](docs/PROJECT.md), the [project Epic](../../issues/2) and the [foundation ADR](docs/adr/0001-foundation-stack.md).

Current stage: **foundation (#1)**. No external data feed is connected yet; the dashboard shows explicit "data unavailable" states rather than any placeholder value.

## Repository layout

| Path | Contents |
| --- | --- |
| `frontend/` | Next.js 16 + TypeScript + Tailwind UI (Georgian default, English prepared) |
| `backend/app/` | FastAPI read API, ingestion worker, configuration |
| `backend/alembic/` | PostgreSQL migrations |
| `compose.yaml` | Full stack: `db`, `migrate`, `api`, `worker`, `frontend` |
| `scripts/compose-smoke.sh` | End-to-end smoke test used locally and in CI |
| `docs/` | Specification, ADRs, evidence |

## Run the full stack

Requirements: Docker with Compose v2.

```bash
cp .env.example .env        # then replace POSTGRES_PASSWORD
docker compose up --build -d --wait
```

- Dashboard: http://127.0.0.1:3000
- API health: http://127.0.0.1:8000/api/health, readiness: `/api/health/ready`, OpenAPI: `/api/docs`

Ports bind to loopback by default. Data persists in the `db-data` volume; `docker compose down` keeps it, `docker compose down -v` deletes it.

Run the smoke test (clean start, health, unavailable UI state, worker heartbeat, persistence across restart):

```bash
scripts/compose-smoke.sh
```

If Docker Hub rate-limits your network, set `POSTGRES_IMAGE`, `PYTHON_IMAGE` and `NODE_IMAGE` in `.env` to a mirror (see `.env.example`).

## Develop without Docker

Backend (Python 3.12, [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
export WINDCAST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/windcast
uv run alembic upgrade head
uv run uvicorn app.main:app --reload       # API on :8000
uv run python -m app.worker                # worker
TEST_DATABASE_URL=$WINDCAST_DATABASE_URL uv run pytest
uv run ruff check . && uv run mypy app
```

Database tests need `TEST_DATABASE_URL` and reset its `public` schema, so point it at a disposable database. They are skipped without it, except in CI where `WINDCAST_REQUIRE_DB_TESTS=1` turns a skip into a failure.

Frontend (Node 22):

```bash
cd frontend
npm ci
WINDCAST_API_URL=http://localhost:8000 npm run dev
npm run lint && npm run typecheck && npm test && npm run build
```

## Configuration

All configuration comes from environment variables; nothing secret is tracked. See `.env.example`.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `WINDCAST_DATABASE_URL` | api, worker, migrate | SQLAlchemy URL (Compose builds it from `POSTGRES_*`) |
| `WINDCAST_APP_ENV` | api, worker | `production`, `development` or `test` |
| `WINDCAST_ALLOW_FIXTURES` | api, worker | Must be `false` in production; startup fails otherwise |
| `WINDCAST_WORKER_HEARTBEAT_SECONDS` | worker | Heartbeat interval |
| `WINDCAST_WORKER_STALE_AFTER_SECONDS` | api, worker healthcheck | Worker considered not reporting after this |
| `WINDCAST_API_URL` | frontend (server side only) | Backend base URL |

## Data principles

Only the national aggregate published by GSE carries MW. Per-site values are meteorological model products in m/s, never measurements and never MW. Times are stored in UTC and shown in Asia/Tbilisi. See [docs/PROJECT.md](docs/PROJECT.md).

## License

License selection is pending owner review. See the technical specification for the initial decision.
