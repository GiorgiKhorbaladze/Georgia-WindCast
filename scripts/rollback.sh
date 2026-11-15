#!/usr/bin/env bash
# Coordinated rollback: previous code AND the database schema/data that belong to it.
#
#   scripts/rollback.sh                          undo the last deployment attempt (deploy/last-attempt)
#   scripts/rollback.sh --to <sha> --backup <f>  explicit target revision and its matching backup
#
# Safety rules (review R1 on PR #19):
#   - The backup must belong to the target code: its Alembic revision must equal the target
#     image's migration head, otherwise nothing is changed.
#   - Writers stay stopped while the database is replaced. The NEWER code's migrate/api/worker are
#     never started again: frontend, api and worker are stopped and the restore runs with
#     --no-start.
#   - The restore is exact (fresh database swapped in by rename), so tables or columns created by
#     the newer migration cannot survive. The replaced database is kept for salvage.
#   - Before the old stack starts, the database is checked to be at the target head, so the old
#     migrate step has nothing to run; its log is checked afterwards.
# Data written after the backup (e.g. new GSE readings) is not in the restored database; it stays
# in the kept <db>_before_restore_<stamp> database.
#
# Exit codes: 0 rolled back and healthy; 1 failed before the database changed (nothing changed,
# newer stack still running unless it had already failed); 3 failed after the swap (see message).
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z ${WINDCAST_ROLLBACK_COPY:-} ]]; then  # git checkout below may replace this file
  copy="$(mktemp)"
  cp "$0" "$copy"
  WINDCAST_ROLLBACK_COPY=1 WINDCAST_APP_DIR="$PWD" exec bash "$copy" "$@"
fi
cd "${WINDCAST_APP_DIR:-.}"
# shellcheck source=lib/compose.sh
source scripts/lib/compose.sh

die() { echo "ROLLBACK ERROR: $*" >&2; exit "${2:-1}"; }
step() { printf '\n== %s\n' "$*"; }
env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
env_set() {
  if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi
}

to="" backup=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --to) to="$2"; shift 2 ;;
    --backup) backup="$2"; shift 2 ;;
    *) die "usage: scripts/rollback.sh [--to <sha> --backup <file>]" ;;
  esac
done

[[ -f .env ]] || die ".env missing"
[[ $(compose_files) == *compose.prod.yaml* ]] || die "COMPOSE_FILE in .env must include compose.prod.yaml"
if [[ -z $to || -z $backup ]]; then
  [[ -s deploy/last-attempt ]] || die "no deploy/last-attempt; pass --to <sha> --backup <file>"
  read -r attempted from_sha recorded_backup < deploy/last-attempt
  [[ $from_sha != "-" && $recorded_backup != "-" ]] ||
    die "the last attempt ($attempted) was a first deployment: there is no earlier revision to return to"
  to="${to:-$from_sha}"
  backup="${backup:-$recorded_backup}"
  echo "undoing attempt $attempted -> back to $to with $backup"
fi
[[ -s $backup ]] || die "backup $backup missing or empty"
current_sha="$(git rev-parse HEAD)"
current_tag="$(env_get WINDCAST_IMAGE_TAG)"

step "Resolving target revision $to"
git fetch --quiet origin || true
sha="$(git rev-parse --verify "$to^{commit}")" || die "unknown revision $to"
tag="${sha:0:12}"
for img in windcast-backend windcast-frontend; do
  docker image inspect "$img:$tag" >/dev/null 2>&1 ||
    die "image $img:$tag is not on this host; rebuild it first: git worktree add /tmp/wc-$tag $sha && (cd /tmp/wc-$tag && WINDCAST_IMAGE_TAG=$tag docker compose build)"
done
if [[ $(compose_files) == *compose.public.yaml* ]]; then
  docker image inspect "windcast-caddy:$tag" >/dev/null 2>&1 || die "image windcast-caddy:$tag is not on this host"
fi

step "Checking that the backup belongs to the target code"
if ! "${DC[@]}" exec -T db pg_restore --list < "$backup" >/dev/null 2>&1; then
  die "$backup is not a valid pg_dump archive"
fi
archive_rev="$("${DC[@]}" exec -T db pg_restore --data-only --table=alembic_version -f - < "$backup" |
  awk '/^COPY .*alembic_version/ {getline; print; exit}')"
target_head="$(docker run --rm --entrypoint alembic "windcast-backend:$tag" heads | awk '{print $1; exit}')"
echo "backup schema revision: ${archive_rev:-?}; target code head: ${target_head:-?}"
[[ -n $archive_rev && $archive_rev == "$target_head" ]] ||
  die "backup revision ($archive_rev) does not match the target code's head ($target_head); nothing changed"

step "Stopping frontend, api and worker (the newer code is not started again)"
"${DC[@]}" stop frontend api worker

step "Exact restore into a fresh database, swapped in by rename"
if ! scripts/restore.sh --exact --no-start "$backup"; then
  die "restore failed; the database is unchanged. The newer stack is stopped: start it again with 'docker compose up -d --wait' (revision $current_sha, tag $current_tag) or fix the archive" 1
fi

step "Selecting the target code and images ($sha)"
git checkout --quiet --detach "$sha"
env_set WINDCAST_IMAGE_TAG "$tag"
db_rev="$("${DC[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"')"
[[ $db_rev == "$target_head" ]] ||
  die "database is at $db_rev, expected $target_head; services left stopped (previous database kept, see above)" 3
echo "database at $db_rev = target head: the target's migrate step has nothing to apply"

step "Starting the target stack"
"${DC[@]}" up -d --wait --wait-timeout 300 --remove-orphans ||
  die "target stack did not become healthy; inspect 'docker compose logs'. The replaced database is kept (see above)" 3
migrate_log="$("${DC[@]}" logs --no-log-prefix migrate 2>&1 || true)"  # no pipe: avoid SIGPIPE
if grep -q "Running upgrade" <<<"$migrate_log"; then
  die "a migration ran during rollback, which must not happen; inspect 'docker compose logs migrate'" 3
fi
[[ $(api_publication) == unpublished ]] || die "the API port is published: check COMPOSE_FILE" 3
"${DC[@]}" exec -T frontend wget -qO- http://127.0.0.1:3000/healthz >/dev/null ||
  die "frontend health check failed" 3

mkdir -p deploy
printf '%s %s %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sha" "$tag" "rollback-from:${current_sha}" "$backup" >> deploy/history.log
rm -f deploy/last-attempt
step "Rolled back to $sha (database revision $db_rev)"
echo "The replaced database is kept for salvage; list with:"
echo "  docker compose exec db psql -U \"\$POSTGRES_USER\" -d postgres -c '\\l'"
