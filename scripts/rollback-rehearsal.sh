#!/usr/bin/env bash
# Cross-version rollback rehearsal (review R1 on PR #19). Runs entirely in a throwaway clone and
# an isolated Compose project; never touches a real deployment.
#
#   A = this repository's HEAD (schema 0003)
#   B = A + migration 0004_rehearsal (new table + new column: incompatible with A's schema)
#   C = A + migration 0004_broken (creates a table, then fails)
#
# Scenario 1: deploy A -> sentinel row -> deploy B (writes post-B data) -> rollback.sh
#   expect: exact A schema (fingerprint equal), sentinel present, B's table/column absent,
#           alembic 0003, A's images running and healthy, no migration ran during rollback,
#           API and database unpublished.
# Scenario 2: deploy C fails at its migration -> rollback.sh -> same expectations.
#
# Images are built here (only the backend differs between A, B and C) and deploy.sh runs with
# DEPLOY_SKIP_BUILD=1. REHEARSAL_BUILD_FLAGS adds docker build flags (e.g. proxy secrets).
# Usage: scripts/rollback-rehearsal.sh        (KEEP=1 keeps the clone and stack for inspection)
set -euo pipefail
src="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
project="windcast-rollback-rehearsal"
read -r -a build_flags <<<"${REHEARSAL_BUILD_FLAGS:-}"
step() { printf '\n######## %s\n' "$*"; }
fail() { echo "REHEARSAL FAILED: $*" >&2; exit 1; }

cleanup() {
  if [[ ${KEEP:-0} != 1 ]]; then
    (cd "$work/app" 2>/dev/null && docker compose down -v --remove-orphans >/dev/null 2>&1) || true
    rm -rf "$work"
  else
    echo "kept: $work/app (project $project)"
  fi
}
trap cleanup EXIT

step "Throwaway clone and rehearsal revisions"
git clone --quiet "$src" "$work/app"
cd "$work/app"
git checkout --quiet --detach "$(git -C "$src" rev-parse HEAD)"
git config user.email rehearsal@example.invalid
git config user.name "rollback rehearsal"
A="$(git rev-parse HEAD)"
versions=backend/alembic/versions

git checkout --quiet -b rehearsal-b "$A"
cat > "$versions/0004_rehearsal.py" <<'PY'
"""Rehearsal only: incompatible schema change (new table and column)."""

import sqlalchemy as sa

from alembic import op

revision = "0004_rehearsal"
down_revision = "0003_weather"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("rollback_probe", sa.Column("id", sa.Integer, primary_key=True))
    op.add_column("source_status", sa.Column("probe_note", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("source_status", "probe_note")
    op.drop_table("rollback_probe")
PY
git add -A && git commit --quiet -m "rehearsal B: incompatible migration"
B="$(git rev-parse HEAD)"

git checkout --quiet -b rehearsal-c "$A"
cat > "$versions/0004_broken.py" <<'PY'
"""Rehearsal only: a migration that fails halfway."""

import sqlalchemy as sa

from alembic import op

revision = "0004_broken"
down_revision = "0003_weather"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("half_done", sa.Column("id", sa.Integer, primary_key=True))
    op.execute("SELECT 1/0")


def downgrade() -> None:
    op.drop_table("half_done")
PY
git add -A && git commit --quiet -m "rehearsal C: broken migration"
C="$(git rev-parse HEAD)"
git checkout --quiet --detach "$A"
echo "A=$A"; echo "B=$B"; echo "C=$C"

step "Building images (frontend once, backend per revision)"
# REHEARSAL_FRONTEND_IMAGE reuses an existing frontend image (the frontend is identical in A/B/C).
frontend_id="${REHEARSAL_FRONTEND_IMAGE:-$(docker build -q "${build_flags[@]}" ${NODE_IMAGE:+--build-arg NODE_IMAGE=$NODE_IMAGE} frontend)}"
for rev in "$A" "$B" "$C"; do
  git checkout --quiet --detach "$rev"
  docker build -q "${build_flags[@]}" ${PYTHON_IMAGE:+--build-arg PYTHON_IMAGE=$PYTHON_IMAGE} \
    -t "windcast-backend:${rev:0:12}" backend >/dev/null
  docker tag "$frontend_id" "windcast-frontend:${rev:0:12}"
done
git checkout --quiet --detach "$A"

step "Rehearsal environment (production overlay)"
cp .env.example .env && chmod 600 .env
sed -i "s|^POSTGRES_PASSWORD=change-me|POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(24))')|" .env
cat >> .env <<EOF
COMPOSE_PROJECT_NAME=$project
COMPOSE_FILE=compose.yaml:compose.prod.yaml
FRONTEND_PORT=${REHEARSAL_FRONTEND_PORT:-13300}
${POSTGRES_IMAGE:+POSTGRES_IMAGE=$POSTGRES_IMAGE}
EOF
export DEPLOY_SKIP_BUILD=1
docker compose down -v --remove-orphans >/dev/null 2>&1 || true

psql_q() { docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$0"' "$1"; }
fingerprint() {  # schema fingerprint: every column of every public table + alembic revision
  psql_q "SELECT md5(string_agg(table_name||'.'||column_name||':'||data_type, ',' ORDER BY table_name, column_name)) FROM information_schema.columns WHERE table_schema='public'"
}
expect_a_state() {  # expect_a_state <label> <fingerprint_A>
  local fp; fp="$(fingerprint)"
  [[ $fp == "$2" ]] || fail "$1: schema fingerprint $fp differs from A ($2)"
  [[ $(psql_q "SELECT version_num FROM alembic_version") == 0003_weather ]] || fail "$1: alembic not at 0003_weather"
  [[ $(psql_q "SELECT count(*) FROM source_status WHERE source='rehearsal-sentinel'") == 1 ]] || fail "$1: sentinel row missing"
  [[ $(psql_q "SELECT count(*) FROM information_schema.tables WHERE table_name IN ('rollback_probe','half_done')") == 0 ]] ||
    fail "$1: tables of the newer migration survived"
  local tag; tag="$(grep -E '^WINDCAST_IMAGE_TAG=' .env | cut -d= -f2)"
  [[ $tag == "${A:0:12}" ]] || fail "$1: image tag $tag, expected ${A:0:12}"
  for svc in api worker frontend; do
    img="$(docker compose ps --format '{{.Image}}' "$svc")"
    [[ $img == *":${A:0:12}" ]] || fail "$1: $svc runs $img, expected tag ${A:0:12}"
  done
  [[ $(docker compose ps --format '{{.Publishers}}' db api) != *"0.0.0.0"* ]] || fail "$1: db or api published"
  docker compose ps --format '{{.Service}} {{.Status}}' | grep -E '^(api|worker|frontend) ' | grep -vq '(healthy)' &&
    fail "$1: a service is not healthy"
  echo "$1: exact A schema ($fp), alembic 0003_weather, sentinel present, A images healthy, db/api unpublished"
}

step "Deploy A and write the sentinel"
scripts/deploy.sh "$A" | tail -3
psql_q "INSERT INTO source_status (source, consecutive_failures) VALUES ('rehearsal-sentinel', 0)" >/dev/null
FP_A="$(fingerprint)"
echo "fingerprint A: $FP_A"

step "Scenario 1: deploy B (incompatible schema), write post-B data, roll back"
bash scripts/deploy.sh "$B" | tail -3
[[ $(psql_q "SELECT version_num FROM alembic_version") == 0004_rehearsal ]] || fail "B did not migrate"
psql_q "INSERT INTO rollback_probe (id) VALUES (1)" >/dev/null
psql_q "UPDATE source_status SET probe_note='written by B' WHERE source='rehearsal-sentinel'" >/dev/null

step "Guard: a backup that does not belong to the target is refused, nothing changes"
wrong="$(scripts/backup.sh backups)"  # taken under B's schema (0004)
rc=0; bash scripts/rollback.sh --to "$A" --backup "$wrong" > "$work/wrong.log" 2>&1 || rc=$?
tail -2 "$work/wrong.log"
[[ $rc != 0 ]] || fail "rollback accepted a backup from a different schema"
grep -q "does not match" "$work/wrong.log" || fail "refusal was not the pairing check"
[[ $(psql_q "SELECT version_num FROM alembic_version") == 0004_rehearsal ]] || fail "refused rollback changed the database"
docker compose ps --format '{{.Service}} {{.Status}}' | grep -E '^(api|worker) ' | grep -vq '(healthy)' &&
  fail "refused rollback disturbed the running services"
rm -f "$wrong"
echo "mismatched backup refused; B still running unchanged"

step "Rollback from B"
bash scripts/rollback.sh
expect_a_state "after rollback from B" "$FP_A"

step "Scenario 2: deploy C (broken migration) must fail, then roll back"
rc=0; bash scripts/deploy.sh "$C" > "$work/deploy-c.log" 2>&1 || rc=$?
tail -3 "$work/deploy-c.log"
[[ $rc != 0 ]] || fail "deploying the broken migration unexpectedly succeeded"
# Capture first: with pipefail, "logs | grep -q" fails by SIGPIPE when grep exits at a match.
migrate_log="$(docker compose logs --no-log-prefix migrate 2>&1 || true)"
grep -qi "division by zero" <<<"$migrate_log" || fail "C did not fail in its migration"
echo "C failed in its migration as intended (division by zero)"
[[ $(psql_q "SELECT version_num FROM alembic_version") == 0003_weather ]] || fail "failed migration left the schema changed"
bash scripts/rollback.sh
expect_a_state "after rollback from failed C" "$FP_A"

step "Kept databases (salvage copies)"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -tAc "SELECT datname FROM pg_database WHERE datname LIKE '"'"'%before_restore%'"'"' ORDER BY 1"'
step "ROLLBACK REHEARSAL PASSED"
