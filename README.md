# Georgia WindCast

Private project for monitoring Georgia's aggregate wind generation and site-level model wind. See the [technical specification and roadmap](docs/PROJECT.md), the [project Epic](../../issues/2) and the [foundation ADR](docs/adr/0001-foundation-stack.md).

An informational web application that shows:

- **Actual national wind generation (MW)** from GSE's public 3-minute exports, with source timestamp, freshness, quality code and collected history. Verification: [docs/sources/gse.md](docs/sources/gse.md).
- **Model wind (m/s)** at three verified wind farm locations (Ruisi, Zemo Wind, Kartli/Gori): DWD ICON forecasts (72 h, 10/80/120/180 m) and ERA5 reanalysis (10/100 m) via Open-Meteo. Verification: [docs/sources/sites.md](docs/sources/sites.md), [docs/sources/weather.md](docs/sources/weather.md).
- A dark interactive map (MapLibre, OpenFreeMap basemap), history and forecast charts (Apache ECharts), and a Georgian/English UI.

Both data sources ship **disabled** (`WINDCAST_GSE_INGESTION_ENABLED`, `WINDCAST_WEATHER_INGESTION_ENABLED`) until the owner confirms the reuse/licence terms. While a source is off or failing, the UI shows explicit unavailable or stale states, never placeholder values. No per-plant MW and no MW forecast exist anywhere in the application. Operations: [docs/OPERATIONS.md](docs/OPERATIONS.md). Public HTTPS deployment on Oracle Cloud Always Free: [docs/DEPLOY-ORACLE.md](docs/DEPLOY-ORACLE.md); launch gates: [docs/PUBLIC-LAUNCH-CHECKLIST.md](docs/PUBLIC-LAUNCH-CHECKLIST.md).

**Streamlit demo edition:** `streamlit_app/` is a separate, database-free demo for Streamlit Community Cloud (latest GSE value plus a 3-hour in-memory window, and the current Open-Meteo forecast). Unlike the Docker stack, it contacts GSE and Open-Meteo whenever it runs (owner decision, 2026-11-16). Deployment and limits: [docs/STREAMLIT.md](docs/STREAMLIT.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `frontend/` | Next.js 16 + TypeScript + Tailwind UI (Georgian default, English prepared) |
| `backend/app/` | FastAPI read API, ingestion worker, configuration |
| `backend/alembic/` | PostgreSQL migrations |
| `compose.yaml` | Full stack: `db`, `migrate`, `api`, `worker`, `frontend` |
| `scripts/compose-smoke.sh` | Compose smoke test used locally and in CI (isolated project) |
| `scripts/backup.sh`, `scripts/restore.sh` | Database backup/restore for a running stack |
| `compose.prod.yaml` | Production overlay (API unpublished, log rotation, limits) |
| `compose.public.yaml`, `deploy/caddy/` | Public edge overlay: Caddy with automatic HTTPS and per-IP rate limits |
| `scripts/edge-smoke.sh` | Public-edge smoke test (HTTPS, exposure, rate limits, status contract) |
| `scripts/host-setup.sh`, `scripts/deploy.sh`, `scripts/rollback.sh`, `scripts/backup-rotate.sh` | Host preparation, exact-SHA deploy, coordinated rollback (code + paired backup), daily backups |
| `scripts/rollback-rehearsal.sh` | Cross-schema rollback rehearsal (CI job) |
| `frontend/e2e/` | Playwright browser tests (desktop + mobile, axe accessibility) |
| `streamlit_app/`, `.streamlit/` | Database-free Streamlit demo edition ([docs/STREAMLIT.md](docs/STREAMLIT.md)) |
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

Run the smoke test (clean start, health, unavailable UI state, worker heartbeat, persistence across restart, migration round trip). It uses its own Compose project (`windcast-smoke`), a random password and ports 18000/13000, so it never touches your stack:

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

Browser tests (Playwright) run against a started stack on a seeded **test** database:

```bash
cd backend && WINDCAST_APP_ENV=test WINDCAST_DATABASE_URL=... uv run python -m tests.e2e_seed
cd frontend && BASE_URL=http://127.0.0.1:3000 npx playwright test
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
| `WINDCAST_GSE_INGESTION_ENABLED` | worker, api | Enable GSE polling (default `false`) |
| `WINDCAST_GSE_POLL_SECONDS` | worker | Poll interval, default 60 s (only due, unstored periods are requested) |
| `WINDCAST_GSE_FRESH_WITHIN_SECONDS` | api | Reading older than this, by its GSE label, is stale (default 600 s) |
| `WINDCAST_GSE_USER_AGENT` | worker | Optional identifying User-Agent for GSE requests |
| `WINDCAST_WEATHER_INGESTION_ENABLED` | worker, api | Enable Open-Meteo weather (default `false`; non-commercial terms) |
| `WINDCAST_WEATHER_POLL_SECONDS` | worker | Model-run check interval, default 900 s (forecast fetched only for a new run) |
| `WINDCAST_LOG_LEVEL` | api, worker | `INFO` by default |
| `WINDCAST_IMAGE_TAG` | compose | Image tag (use a git SHA for rollback) |

Verify the live sources at any time (read only, no database writes): `cd backend && uv run python -m app.ingestion.live_check` (GSE) and `uv run python -m app.ingestion.live_check_weather` (Open-Meteo), or run the manual **Live source check** workflow.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health`, `/api/health/ready` | Liveness; readiness (DB reachable and migrated) |
| `GET /api/v1/generation/latest` | National wind MW with freshness (`fresh`/`stale`/`unavailable`), source label time, retrieval time and quality code |
| `GET /api/v1/generation/history?start=&end=` | Collected readings (max 31 days), `collection_started_at`, and explicit `gaps` (never interpolated) |
| `GET /api/v1/status` | Worker liveness, source availability and backoff state, tracked sites |
| `GET /api/v1/weather` | Model "now" values per site/height, forecast run, horizon and freshness, supported heights |
| `GET /api/v1/weather/sites/{id}?height=&start=&end=` | Per-site series: past (shortest-lead runs), forecast (latest run, 72 h), ERA5 reanalysis; unsupported heights flagged |

## Data principles

Only the national aggregate published by GSE carries MW. Per-site values are meteorological model products in m/s, never measurements and never MW. Times are stored in UTC and shown in Asia/Tbilisi. See [docs/PROJECT.md](docs/PROJECT.md).

## License

License selection is pending owner review. See the technical specification for the initial decision.
