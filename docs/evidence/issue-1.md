# Issue #1 verification

Local environment: Node 24.22.1, Python 3.12.14, Docker 29.9.2 with rootless VFS.
CI pins Node 22.21.1, Python 3.12.12 and uv 0.9.9, matching the container runtimes.

Commands and results:

- `npm ci`: installed the frontend lockfile.
- `npm run lint`: passed.
- `npm run typecheck`: passed.
- `npm run build`: passed, including Next.js TypeScript checks and static generation.
- `npm audit --omit=dev --audit-level=high`: passed, zero vulnerabilities.
- `uv sync --frozen`: passed.
- `uv run --frozen ruff check .`: passed.
- `uv run --frozen ruff format --check .`: passed (8 files).
- `uv run --frozen pytest -q`: passed (5 tests); Starlette emits an upstream
  AnyIO deprecation warning.
- `bash -n scripts/compose-smoke.sh` and `git diff --check`: passed.

## Cloud environment adjustments

The local cloud proxy uses a session CA which container package managers do not
inherit. Temporary Dockerfile copies mounted the combined system CA as a
BuildKit secret for `npm ci` / `uv sync`; TLS verification remained enabled.
The certificate and temporary overrides are not committed or baked into images.

The 8 GB local filesystem and Docker's VFS driver could not hold both build cache
and running containers. After building the exact application sources, unused
build cache was removed and a temporary Compose override selected those built
images without rebuilding. The local images were then flattened via
`docker export` / `docker import`, preserving their root filesystems and runtime
configuration, to remove redundant VFS layers. This is a local-only adjustment;
CI builds the original Dockerfiles. The official PostgreSQL Alpine image reduces storage
requirements and remains standard PostgreSQL, as recorded in ADR 0001. CI runs
the unmodified default Compose build and smoke command on a clean runner.

The transcript includes startup, availability assertions, a full stack recreation
and persisted sentinel read, and Alembic downgrade/upgrade. See the PR body for
its exact head SHA and the corresponding GitHub Actions run links.

## Local Compose result

`COMPOSE_FILE=compose.yaml:/tmp/windcast-docker/prebuilt.yaml bash scripts/compose-smoke.sh`
completed with exit code 0. All services were healthy, unavailable-state checks
passed, the sentinel survived stack recreation, and migrations round-tripped.
The temporary override changed build/image selection only, as described above.
[Full passing transcript](local-compose-smoke.txt).
