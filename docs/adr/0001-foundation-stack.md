# ADR 0001 - Foundation stack and repository layout

- Status: Proposed (owner approval pending via PR for issue #1)
- Date: 2026-11-14

## Context

Issue #1 asks for a reproducible monorepo: Next.js/TypeScript/Tailwind frontend, FastAPI backend,
a separate worker, PostgreSQL with migrations, Docker Compose and GitHub Actions. The
specification (`docs/PROJECT.md`) asks that deviations be recorded in an ADR.

## Decision

| Layer | Choice | Version pinned by |
| --- | --- | --- |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 | `frontend/package-lock.json` |
| Backend API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 | `backend/uv.lock` |
| Worker | Same image as API, `python -m app.worker` | `backend/uv.lock` |
| Database | PostgreSQL 17 (`postgres:17.12-alpine3.24`), Alembic migrations | `compose.yaml`, `backend/alembic/` |
| Orchestration | Docker Compose, one-shot `migrate` service | `compose.yaml` |
| CI | GitHub Actions `CI` workflow | `.github/workflows/ci.yml` |

Layering: `frontend/` only reads the backend over HTTP; `backend/app/api` exposes read endpoints;
`backend/app/worker.py` is the only process that will write source data; migrations run once per
deployment in the `migrate` service before `api` and `worker` start.

### Stable CI check names

- `Frontend (lint, typecheck, unit, build)`
- `Backend (lint, typecheck, tests, migrations)`
- `Compose smoke`
- `Repository checks` (pre-existing workflow, retained)

### Choices that need explicit note

1. **No Next.js Cache Components.** The `create-next-app` template enabled `cacheComponents`
   and `partialPrefetching`. They were removed: every WindCast view depends on request-time
   data and on the language cookie, and a prerendered shell would add the risk of serving an
   outdated value. All pages render per request and backend calls use `cache: "no-store"`.
2. **Server-side data access only.** The browser does not call the backend directly in this stage.
   `WINDCAST_API_URL` is read on the Next.js server, so no backend address or credential reaches the
   client bundle, and no CORS opening is needed.
3. **Self-hosted fonts** via `@fontsource` (Inter, Noto Sans Georgian, JetBrains Mono) instead of
   `next/font/google`, so builds do not depend on Google Fonts availability.
4. **Fixture guard.** `WINDCAST_ALLOW_FIXTURES=true` is rejected at startup when
   `WINDCAST_APP_ENV=production`; Compose hard-codes `WINDCAST_ALLOW_FIXTURES=false`. Fixtures live
   only under `backend/tests/`. The frontend contains no fixture data at all.
5. **Language switch** is a Server Action that sets a `windcast_lang` cookie (Georgian default,
   English prepared). It works without client JavaScript.
6. **Base images are build arguments** (`PYTHON_IMAGE`, `NODE_IMAGE`, `POSTGRES_IMAGE`) defaulting to
   official Docker Hub images, so a registry mirror can be used where Docker Hub rate-limits.
7. **Optional `extra_ca` build secret** for networks with TLS inspection. It is a no-op when absent
   and never copied into an image layer.

## Reconciliation with the alternative foundation (PR #11)

Two independent foundations were opened for issue #1 (#10 and #11). Both pass CI. This
foundation (#10) was kept as the base because it is further along on every axis that later
issues depend on. It has real-database tests (21 vs. 5 mocked), strict typing, a readiness check
that verifies the Alembic head, a production fixture guard, frontend unit tests and an API-backed
bilingual UI. Four capabilities that existed only in #11 were adopted:

1. The smoke test runs in an isolated Compose project with a random password and non-default
   ports. The previous smoke test used the default project and `down -v`, which would have deleted
   a developer's local database.
2. Migration downgrade/upgrade round trip inside the Compose stack.
3. CI uploads the smoke transcript as an artifact.
4. Exactly pinned base images (`postgres:17.12-alpine3.24`, `python:3.12.16-slim`,
   `node:22.23.5-alpine3.24`) and PostgreSQL 17 instead of 16 (longer support window; no data
   existed yet, so no migration cost).

Not adopted from #11: unprefixed health paths (`/health/*`; this API keeps everything under
`/api`), raw-psycopg data access (SQLAlchemy is used for migrations and models), and copying the
`uv` binary from GHCR (blocked in some networks; a pinned PyPI install is equivalent).

## Consequences

- One backend image serves `migrate`, `api` and `worker`, so they cannot drift in version.
- Readiness (`/api/health/ready`) fails with HTTP 503 until the schema is at the Alembic head;
  liveness (`/api/health`) never touches the database.
- No upstream data source is contacted by CI. Live-source checks will be a separate, manually
  triggered job introduced with issue #3.

## Open points for the owner

- Georgian display names of the three sites (`backend/app/sites.py`) need confirmation, in
  particular the Georgian form of "Zemo Wind".
- Hosting target for the private pilot is deferred to issue #9.
