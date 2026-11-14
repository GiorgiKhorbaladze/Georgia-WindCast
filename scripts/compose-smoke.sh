#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Run in an isolated project; never delete the development database.
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-windcast-smoke}"
export POSTGRES_USER=windcast POSTGRES_DB=windcast
export POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export API_PORT="${API_PORT:-18000}" FRONTEND_PORT="${FRONTEND_PORT:-13000}"
export WORKER_INTERVAL_SECONDS=1
cleanup() {
  docker compose logs --no-color
  docker compose down --volumes --remove-orphans
}
trap cleanup EXIT
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
curl --fail --silent "http://localhost:$API_PORT/health/live"
curl --fail --silent "http://localhost:$API_PORT/health/ready"
curl --fail --silent "http://localhost:$API_PORT/api/status" | python3 -c '
import json,sys
s=json.load(sys.stdin)
assert s["generation"] == {"status":"unavailable", "value_mw":None}
assert s["weather"] == {"status":"unavailable", "sites":[]}
print("API unavailable states: PASS")'
curl --fail --silent "http://localhost:$FRONTEND_PORT" | python3 -c '
import sys
html=sys.stdin.read()
assert "Unavailable" in html and "Georgia WindCast" in html
print("Frontend production startup: PASS")'
docker compose exec -T db psql -U windcast -d windcast -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE smoke_persistence (id integer PRIMARY KEY); INSERT INTO smoke_persistence VALUES (42);"
docker compose down
docker compose up -d --wait --wait-timeout 180
test "$(docker compose exec -T db psql -U windcast -d windcast -Atc 'SELECT id FROM smoke_persistence')" = 42
echo 'Database persistence across stack recreation: PASS'
docker compose stop api worker
docker compose run --rm migrate alembic downgrade base
docker compose run --rm migrate alembic upgrade head
docker compose up -d --wait --wait-timeout 180
docker compose exec -T api python -c 'from app.db import ready; ready(); print("Migration downgrade/upgrade: PASS")'
echo 'COMPOSE SMOKE: PASS'
