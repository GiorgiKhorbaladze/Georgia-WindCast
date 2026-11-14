# Georgia WindCast

Private project for monitoring Georgia’s aggregate wind generation and site-level model wind. See the [technical specification and roadmap](docs/PROJECT.md), [project Epic](../../issues/2), and [Claude Code’s first assignment](../../issues/1).

License selection is pending owner review. See the technical specification for the initial decision.

## Run the foundation

Requirements: Docker Engine with Compose v2, Python 3 (smoke helper), and curl.
For development checks use Node 22.21.1, Python 3.12 and uv 0.9.9.

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD in .env to a unique URL-safe value (e.g. 48 hex digits).
# Generate one with: python3 -c 'import secrets; print(secrets.token_hex(24))'
docker compose up --build -d --wait
curl --fail http://localhost:8000/health/ready
```

Open http://localhost:3000. The UI explicitly shows unavailable generation and
weather; no fixtures or external feeds run in this foundation. The API exposes
`/health/live`, database/schema readiness at `/health/ready` (503 if unavailable),
and `/api/status`. Worker health is a database heartbeat, not a data observation.
PostgreSQL stores timezone-aware UTC timestamps. Data display uses Asia/Tbilisi.

`docker compose down` stops the stack and preserves the named database volume.
`docker compose up -d --wait` restarts it. **`docker compose down --volumes`
deletes local database data.** Migration runs automatically before API and worker.
Inspect logs with `docker compose logs`; inspect migration state with
`docker compose run --rm migrate alembic current`. Password changes in `.env`
do not change credentials in an existing database volume. Keep `.env` private.

## Verification

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
cd ../backend
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest -q
cd ..
bash scripts/compose-smoke.sh 2>&1 | tee /tmp/windcast-compose-smoke.txt
```

The smoke test uses its own `windcast-smoke` Compose project, generated credentials,
and ports 13000/18000. It removes only that project's volumes on exit. Do not run
it concurrently with another smoke test; override `COMPOSE_PROJECT_NAME`,
`FRONTEND_PORT` and `API_PORT` if needed. It verifies service health, production
UI and API unavailable states, worker startup, persistence across full stack
recreation, and migration downgrade/upgrade. CI attaches its transcript as an
artifact. Dependencies are pinned in `frontend/package-lock.json` and
`backend/uv.lock`; use `npm ci` and `uv sync --frozen` to reproduce them.

Stable PR checks: `Repository checks`, `Frontend lint / type / build`,
`Backend lint / tests`, and `Migrations / Compose smoke`.
See [foundation decisions](docs/ADR-0001-foundation.md). No merge or deployment
is authorized by green checks; owner approval is required.
