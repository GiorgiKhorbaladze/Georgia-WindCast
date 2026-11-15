#!/usr/bin/env bash
# Compose smoke test with the PRODUCTION overlay (compose.yaml + compose.prod.yaml):
# clean start, API unpublished, health/readiness (from inside the network), UI unavailable state,
# worker heartbeat, persistence across stack recreation, migration round trip, invalid-archive
# rejection, a failing restore that must roll back with services restored and the API still
# unpublished, and a successful backup/restore.
#
# Runs in an isolated Compose project ("windcast-smoke") with a random database password and a
# non-default frontend port, so it can never touch or delete a developer's own stack or data.
#
# Usage: scripts/compose-smoke.sh
# Set KEEP_STACK=1 to leave the stack running afterwards.
# Set SMOKE_SKIP_BUILD=1 to test already-built windcast-backend/frontend:local images.
set -euo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME="${SMOKE_PROJECT_NAME:-windcast-smoke}"
export COMPOSE_FILE="compose.yaml:compose.prod.yaml"
export POSTGRES_USER=windcast POSTGRES_DB=windcast
POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export POSTGRES_PASSWORD
export FRONTEND_PORT="${SMOKE_FRONTEND_PORT:-13000}"
export WINDCAST_WORKER_HEARTBEAT_SECONDS=2
WEB="http://127.0.0.1:${FRONTEND_PORT}"
# shellcheck source=lib/compose.sh
source scripts/lib/compose.sh

step() { printf '\n== %s\n' "$*"; }

dump_state() {
  "${DC[@]}" ps >&2 || true
  "${DC[@]}" logs --tail=80 >&2 || true
}

wait_for() {  # wait_for <url> <seconds> [expected-substring]   (host-side, frontend only)
  local url=$1 timeout=$2 expect=${3:-} body
  for ((i = 0; i < timeout; i++)); do
    if body=$(curl -fsS --max-time 3 "$url" 2>/dev/null); then
      if [[ -z $expect || $body == *"$expect"* ]]; then
        printf '%s\n' "$body"
        return 0
      fi
    fi
    sleep 1
  done
  echo "TIMEOUT waiting for $url (expect: ${expect:-any 2xx})" >&2
  dump_state
  return 1
}

api_get() {  # GET an API path from inside the api container (the API is not published)
  "${DC[@]}" exec -T api python -c \
    'import sys,urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000"+sys.argv[1], timeout=5).read().decode())' "$1"
}

api_wait() {  # api_wait <path> <seconds> <expected-substring>
  local body
  for ((i = 0; i < $2; i++)); do
    if body=$(api_get "$1" 2>/dev/null) && [[ $body == *"$3"* ]]; then
      printf '%s\n' "$body"
      return 0
    fi
    sleep 1
  done
  echo "TIMEOUT waiting for API $1 (expect: $3)" >&2
  dump_state
  return 1
}

assert_api_unpublished() {
  if [[ $(api_publication) != unpublished ]]; then
    echo "FAIL: the API port is published" >&2
    "${DC[@]}" ps api >&2
    exit 1
  fi
  echo "API port 8000 is not published on the host"
}

psql_scalar() {
  "${DC[@]}" exec -T db sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$0"' "$1"
}

cleanup() {
  if [[ ${KEEP_STACK:-0} != 1 ]]; then
    step "Tearing down (volumes removed)"
    "${DC[@]}" down -v --remove-orphans
  fi
}
trap cleanup EXIT

step "Building and starting a clean stack (project: $COMPOSE_PROJECT_NAME, files: $COMPOSE_FILE)"
"${DC[@]}" config --quiet
"${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
build_flag=(--build)
[[ ${SMOKE_SKIP_BUILD:-0} == 1 ]] && build_flag=()
"${DC[@]}" up "${build_flag[@]}" -d --wait --wait-timeout 240

step "Production overlay: API not published"
assert_api_unpublished

step "API liveness and readiness (from inside the network)"
api_wait /api/health 60 '"status":"ok"'
api_wait /api/health/ready 60 '"status":"ready"'

step "Generation endpoint reports unavailable with no value"
gen=$(api_get /api/v1/generation/latest)
echo "$gen"
[[ $gen == *'"freshness":"unavailable"'* && $gen == *'"value_mw":null'* ]]

step "Worker heartbeat recorded"
api_wait /api/v1/status 60 '"state":"running"' | head -c 300
echo

step "Frontend renders explicit unavailable state (Georgian default) and proxies status"
html=$(wait_for "$WEB/" 60 'GEORGIA WINDCAST')
grep -q 'მონაცემები მიუწვდომელია' <<<"$html"
echo "dashboard OK ($(wc -c <<<"$html") bytes)"
wait_for "$WEB/healthz" 30 '"status":"ok"'
wait_for "$WEB/api/data/status" 30 '"worker"' | head -c 200
echo

step "Persistence: record instance timestamp, recreate the full stack, compare"
before=$(psql_scalar "SELECT installed_at FROM instance_metadata WHERE id = 1")
echo "installed_at before: $before"
"${DC[@]}" down            # containers removed, named volume kept
"${DC[@]}" up -d --wait --wait-timeout 180
api_wait /api/health/ready 60 '"status":"ready"' >/dev/null
after=$(psql_scalar "SELECT installed_at FROM instance_metadata WHERE id = 1")
echo "installed_at after:  $after"
[[ -n $before && $before == "$after" ]]
assert_api_unpublished

step "Migration round trip (downgrade to base, upgrade to head) against the Compose database"
"${DC[@]}" stop api worker
"${DC[@]}" run --rm migrate alembic downgrade base
"${DC[@]}" run --rm migrate alembic upgrade head
"${DC[@]}" up -d --wait --wait-timeout 180
api_wait /api/health/ready 60 '"status":"ready"'

backup_dir="$(mktemp -d)"
step "Backup"
dump="$(scripts/backup.sh "$backup_dir")"
echo "backup: $dump ($(wc -c <"$dump") bytes)"
psql_scalar "INSERT INTO source_status (source, consecutive_failures) VALUES ('smoke-marker', 0)" >/dev/null

step "Invalid archive is rejected before anything changes"
head -c 100 "$dump" > "$backup_dir/truncated.dump"
rc=0; scripts/restore.sh "$backup_dir/truncated.dump" || rc=$?
echo "restore rc=$rc"
[[ $rc -eq 2 ]]
[[ $(psql_scalar "SELECT count(*) FROM source_status WHERE source = 'smoke-marker'") == 1 ]]
api_wait /api/health/ready 30 '"status":"ready"' >/dev/null

step "Failing restore rolls back completely; services come back; API stays unpublished"
# A dependent view makes DROP TABLE fail mid-restore; the single transaction must roll back.
psql_scalar "CREATE VIEW smoke_dependent_view AS SELECT * FROM source_status" >/dev/null
rc=0; scripts/restore.sh "$dump" || rc=$?
echo "restore rc=$rc"
[[ $rc -eq 1 ]]
[[ $(psql_scalar "SELECT count(*) FROM source_status WHERE source = 'smoke-marker'") == 1 ]]
[[ $(psql_scalar "SELECT count(*) FROM pg_views WHERE viewname = 'smoke_dependent_view'") == 1 ]]
api_wait /api/health/ready 60 '"status":"ready"' >/dev/null
assert_api_unpublished
psql_scalar "DROP VIEW smoke_dependent_view" >/dev/null
echo "failed restore preserved data and service readiness"

step "Successful restore: the row added after the backup disappears"
scripts/restore.sh "$dump"
[[ $(psql_scalar "SELECT count(*) FROM source_status WHERE source = 'smoke-marker'") == 0 ]]
api_wait /api/health/ready 60 '"status":"ready"' >/dev/null
assert_api_unpublished
rm -rf "$backup_dir"
echo "restore verified"

step "SMOKE PASSED"
