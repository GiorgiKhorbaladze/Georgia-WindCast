# Operations guide - private pilot

Scope: issue #9. This guide covers deploying, monitoring, backing up and rolling back WindCast on a single private host. **No public exposure, paid service or release is implied.** Those need the owner's explicit authorisation.

## 1. Deployment checklist

| # | Step | How to verify |
| --- | --- | --- |
| 1 | Host with Docker Engine and Compose v2 (2 vCPU, 4 GB RAM and 20 GB disk are ample) | `docker compose version` |
| 2 | Clone the repository at an approved, merged commit; note its SHA | `git rev-parse HEAD` |
| 3 | `cp .env.example .env`; set a strong `POSTGRES_PASSWORD` (`openssl rand -hex 24`) | `.env` not tracked (`git status`) |
| 4 | Set `WINDCAST_IMAGE_TAG=<git SHA>` | `docker compose config \| grep image:` |
| 5 | Decide the data sources: `WINDCAST_GSE_INGESTION_ENABLED` (needs GSE reuse confirmation) and `WINDCAST_WEATHER_INGESTION_ENABLED` (needs Open-Meteo use category confirmation) | See `docs/sources/gse.md` §9, `docs/sources/weather.md` |
| 6 | Build and start: `docker compose -f compose.yaml -f compose.prod.yaml up --build -d --wait` | all services `healthy` in `docker compose ps` |
| 7 | Readiness: `docker compose exec api python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready').read())"` | `"status":"ready"` |
| 8 | Put a TLS reverse proxy with access control (e.g. Caddy/nginx with basic auth or an SSO proxy, or a VPN) in front of `FRONTEND_BIND:FRONTEND_PORT`. Keep `FRONTEND_BIND=127.0.0.1` | Not reachable without authentication |
| 9 | Schedule backups (§4) and copy them off-host | A dump file exists and a restore test succeeds |
| 10 | Record the deployed SHA, date and operator | Ops log |

Run the full verification before any release: `scripts/compose-smoke.sh`. It covers a clean start, health, persistence, migration round trip and backup/restore, in an isolated project.

## 2. Configuration

All settings are environment variables; `.env.example` documents each one. Secrets exist only in `.env`, as the database password. GSE and Open-Meteo need no credentials. Nothing secret is baked into images.

## 3. Health, monitoring and source status

| Signal | Where | Healthy |
| --- | --- | --- |
| API liveness | `GET /api/health` (container healthcheck) | 200 |
| API readiness | `GET /api/health/ready` | 200 and the schema at the Alembic head |
| Worker liveness | container healthcheck `python -m app.healthcheck` (DB heartbeat newer than `WINDCAST_WORKER_STALE_AFTER_SECONDS`) | healthy |
| Frontend | `GET /healthz` | 200 |
| Source availability | `GET /api/v1/status` → `sources[]`: `state` (`ok`/`degraded`/`down`/`not_configured`), `last_success_at`, `consecutive_failures`, `backoff_until`, `last_error` | `ok` |
| Data freshness | `GET /api/v1/generation/latest` → `freshness`; `GET /api/v1/weather` → `forecast_state` | `fresh` |

The dashboard's "Data sources" panel shows the same states. For alerting, point any uptime monitor at the frontend through the reverse proxy. A cron job such as `curl -fsS .../api/v1/status | jq` can watch for `"down"`. No paid monitoring service is required.

**Error reporting.** Both services log to stdout (`docker compose logs -f api worker`). Ingestion failures are logged at WARNING with the cause and backoff, and are recorded in `source_status.last_error`. Unhandled exceptions are logged with tracebacks and never stop the worker loop. `compose.prod.yaml` rotates logs (5 × 10 MB per service). Set `WINDCAST_LOG_LEVEL=DEBUG` temporarily for diagnosis.

## 4. Backup and restore

```bash
scripts/backup.sh /srv/windcast-backups        # pg_dump -Fc; prints the file path
scripts/restore.sh /srv/windcast-backups/windcast-<UTC>.dump
```

- **What matters:** `generation_reading` holds the collected GSE history. GSE's archive is irregular, so this history **cannot be re-fetched** reliably. Weather can be re-fetched only within the provider's windows.
- **Suggested schedule:** a daily cron at 03:17 local time; keep 14 daily and 8 weekly backups; copy them off-host.
- **Verified:** the smoke test takes a backup, adds a marker row, restores, and asserts the marker is gone and the instance id unchanged. This runs in CI on every PR.

## 5. Upgrade and rollback

Upgrade:
1. `scripts/backup.sh`.
2. `git fetch && git checkout <new SHA>`; set `WINDCAST_IMAGE_TAG=<new SHA>`.
3. `docker compose -f compose.yaml -f compose.prod.yaml up --build -d --wait`. The one-shot `migrate` service applies migrations before `api` and `worker` start.

Rollback, when the new release misbehaves:
1. If the new release added migrations, downgrade them **with the new image** first: `docker compose run --rm migrate alembic downgrade <previous head>`. Revision ids are in `backend/alembic/versions/`. Downgrades are tested in CI (base ↔ head round trip). They can drop tables that only the new release used, which is why step 1 of the upgrade takes a backup.
2. Set `WINDCAST_IMAGE_TAG=<previous SHA>` and `git checkout <previous SHA>`.
3. `docker compose -f compose.yaml -f compose.prod.yaml up -d --wait`. The previous images are reused if still present; otherwise `--build` rebuilds them.
4. If the data is inconsistent, restore the pre-upgrade backup (§4).

## 6. Data retention

- GSE readings: kept indefinitely (about 480 rows a day, under 50 MB a year).
- Weather: values more than 12 h ahead of their run are deleted once the run is older than `weather_forecast_retention_days` (30). Short-lead values are kept as history. Reanalysis is kept.

## 7. Security review (2026-11-14)

| Area | Status |
| --- | --- |
| Secrets | Only `POSTGRES_PASSWORD`, in the untracked `.env`. No API keys. The smoke and CI use random or CI-only passwords |
| Network exposure | Ports bind to `127.0.0.1` by default; `compose.prod.yaml` does not publish the API at all. PostgreSQL is never published. The browser only talks to the frontend, which proxies the read-only API server-side |
| Containers | API, worker and frontend run as non-root users (uid 10001); images use exactly pinned base images |
| HTTP headers | CSP (`default-src 'self'`, tiles host only, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, a strict referrer policy and a restrictive `Permissions-Policy` |
| API surface | GET only (read-only); query parameters validated (range ≤ 31 days, enumerated heights, site id pattern) |
| Input parsing | GSE XML via `defusedxml` (entity expansion forbidden); strict schema; JSON from Open-Meteo validated for units, lengths and ranges |
| Outbound requests | Fixed hosts (GSE, Open-Meteo); no user-controlled URLs (no SSRF surface); redirects not followed |
| Dependencies | Lockfiles (`uv.lock`, `package-lock.json`); CI fails on high/critical advisories in production npm dependencies. Known: moderate advisories in dev-only ESLint tooling |
| Fixtures | Production refuses `WINDCAST_ALLOW_FIXTURES=true`; the E2E seed refuses unless `WINDCAST_APP_ENV=test` and is not in any image |
| Not in place | Authentication (delegated to the reverse proxy or VPN, step 8), rate limiting at the edge, TLS (reverse proxy), automated off-host backups |

## 8. Known limitations

- GSE source: undocumented website data files with no published reuse terms. Quality codes (`NRE`, ...) are unexplained. A future website redesign could change the source again; schema-drift detection makes that visible.
- Open-Meteo: free tier is non-commercial; quota is per IP (10,000 a day).
- No per-plant generation exists or is estimated. No MW forecast is provided.
- Weather is point model data at three representative coordinates (Ruisi ±4 km). The map animation is local to those points, not a wind field.

## 9. Deployment status

No private host or credentials were provided to the implementation agent. A private deployment is therefore **not performed**. Every step above is verified locally and in CI (Compose smoke, including backup/restore and migration round trip). **Blocker:** the owner to choose a host and authorise access (and confirm source terms) before a private pilot.
