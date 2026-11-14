#!/usr/bin/env bash
# Compose smoke test: clean start, health, readiness, UI unavailable state, worker heartbeat,
# and database persistence across a full stack restart.
#
# Usage: scripts/compose-smoke.sh   (expects a .env file; CI copies .env.example)
# Set KEEP_STACK=1 to leave the stack running afterwards.
# Set SMOKE_SKIP_BUILD=1 to test already-built windcast-backend/frontend:local images.
set -euo pipefail

cd "$(dirname "$0")/.."
API="http://127.0.0.1:${API_PORT:-8000}"
WEB="http://127.0.0.1:${FRONTEND_PORT:-3000}"
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

step "Building and starting a clean stack"
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

step "SMOKE PASSED"
