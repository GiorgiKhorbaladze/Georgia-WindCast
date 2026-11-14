#!/usr/bin/env bash
# Compose smoke test: clean start, health, readiness, UI unavailable state, worker heartbeat,
# database persistence across a full stack recreation, and a migration round trip.
#
# Runs in an isolated Compose project ("windcast-smoke") with a random database password and
# non-default ports, so it can never touch or delete a developer's own stack or data.
#
# Usage: scripts/compose-smoke.sh
# Set KEEP_STACK=1 to leave the stack running afterwards.
# Set SMOKE_SKIP_BUILD=1 to test already-built windcast-backend/frontend:local images.
set -euo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME="${SMOKE_PROJECT_NAME:-windcast-smoke}"
export POSTGRES_USER=windcast POSTGRES_DB=windcast
POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export POSTGRES_PASSWORD
export API_PORT="${SMOKE_API_PORT:-18000}" FRONTEND_PORT="${SMOKE_FRONTEND_PORT:-13000}"
export WINDCAST_WORKER_HEARTBEAT_SECONDS=2
API="http://127.0.0.1:${API_PORT}"
WEB="http://127.0.0.1:${FRONTEND_PORT}"
DC=(docker compose)

step() { printf '\n== %s\n' "$*"; }

wait_for() {  # wait_for <url> <seconds> [expected-substring]
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
  "${DC[@]}" ps >&2 || true
  "${DC[@]}" logs --tail=80 >&2 || true
  return 1
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

step "Building and starting a clean stack (project: $COMPOSE_PROJECT_NAME)"
"${DC[@]}" config --quiet
"${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
build_flag=(--build)
[[ ${SMOKE_SKIP_BUILD:-0} == 1 ]] && build_flag=()
"${DC[@]}" up "${build_flag[@]}" -d --wait --wait-timeout 240

step "API liveness"
wait_for "$API/api/health" 60 '"status":"ok"'

step "API readiness (database reachable and migrated)"
wait_for "$API/api/health/ready" 60 '"status":"ready"'

step "Generation endpoint reports unavailable with no value"
gen=$(curl -fsS "$API/api/v1/generation/latest")
echo "$gen"
[[ $gen == *'"freshness":"unavailable"'* && $gen == *'"value_mw":null'* ]]

step "Worker heartbeat recorded"
wait_for "$API/api/v1/status" 60 '"state":"running"' | head -c 400
echo

step "Frontend renders explicit unavailable state (Georgian default)"
html=$(wait_for "$WEB/" 60 'GEORGIA WINDCAST')
grep -q 'მონაცემები მიუწვდომელია' <<<"$html"
echo "dashboard OK ($(wc -c <<<"$html") bytes)"
wait_for "$WEB/healthz" 30 '"status":"ok"'

step "Persistence: record instance timestamp, restart the full stack, compare"
before=$(psql_scalar "SELECT installed_at FROM instance_metadata WHERE id = 1")
echo "installed_at before restart: $before"
"${DC[@]}" down            # containers removed, named volume kept
"${DC[@]}" up -d --wait --wait-timeout 180
wait_for "$API/api/health/ready" 60 '"status":"ready"' >/dev/null
after=$(psql_scalar "SELECT installed_at FROM instance_metadata WHERE id = 1")
echo "installed_at after restart:  $after"
[[ -n $before && $before == "$after" ]]

step "Migration round trip (downgrade to base, upgrade to head) against the Compose database"
"${DC[@]}" stop api worker
"${DC[@]}" run --rm migrate alembic downgrade base
"${DC[@]}" run --rm migrate alembic upgrade head
"${DC[@]}" up -d --wait --wait-timeout 180
wait_for "$API/api/health/ready" 60 '"status":"ready"'

step "SMOKE PASSED"
