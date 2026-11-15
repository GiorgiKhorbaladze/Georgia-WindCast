#!/usr/bin/env bash
# Atomic restore of a backup produced by scripts/backup.sh into the running Compose stack.
#
# Default mode (same code version, e.g. recovering from data loss):
# 1. Validates the archive (pg_restore --list) before anything is touched.
# 2. Stops api and worker (the only writers).
# 3. Restores in ONE transaction (--single-transaction --exit-on-error): any error rolls the whole
#    restore back, so the database is either fully restored or left exactly as it was.
# 4. Always restarts api and worker, on success AND on failure, with the same Compose
#    configuration as startup (COMPOSE_FILE), and verifies the API port publication is unchanged.
#    Starting api/worker runs the CURRENT code's migrations first, so an older archive is brought
#    up to the current schema. To go back to OLDER CODE use scripts/rollback.sh instead.
#
# Options (used by scripts/rollback.sh):
#   --exact     restore into a fresh database and swap it in by renaming, so the result is exactly
#               the archive's schema (objects created after the backup cannot survive). The previous
#               database is kept as <db>_before_restore_<UTC stamp> until an operator drops it.
#   --no-start  stop api, worker and frontend and leave them stopped; the caller starts the
#               intended code version. No migration runs.
#
# Exit codes: 0 restored; 1 restore failed and was rolled back (data unchanged; services running
#             unless --no-start); 2 archive invalid (nothing changed); 3 services did not come back
#             healthy.
# Usage: scripts/restore.sh [--exact] [--no-start] <file.dump>
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=lib/compose.sh
source scripts/lib/compose.sh

exact=0
start=1
while [[ $# -gt 1 ]]; do
  case $1 in
    --exact) exact=1 ;;
    --no-start) start=0 ;;
    *) echo "restore: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
file="${1:?usage: scripts/restore.sh [--exact] [--no-start] <file.dump>}"
test -s "$file" || { echo "restore: $file is missing or empty; nothing changed" >&2; exit 2; }

echo "restore: compose files: $(compose_files || true)"
if ! "${DC[@]}" exec -T db pg_restore --list < "$file" > /dev/null 2>&1; then
  echo "restore: $file is not a valid pg_dump archive; nothing changed" >&2
  exit 2
fi
publication_before="$(api_publication)"

if [[ $start == 1 ]]; then
  "${DC[@]}" stop api worker
else
  "${DC[@]}" stop frontend api worker
fi

restore_rc=0
if [[ $exact == 0 ]]; then
  "${DC[@]}" exec -T db sh -c \
    'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction --exit-on-error' \
    < "$file" || restore_rc=$?
else
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  # Restore into a fresh database first; the live database is untouched until the swap.
  "${DC[@]}" exec -T -e STAMP="$stamp" db sh -c '
    set -e
    createdb -U "$POSTGRES_USER" "${POSTGRES_DB}_restore_${STAMP}"' || restore_rc=$?
  if [[ $restore_rc == 0 ]]; then
    "${DC[@]}" exec -T -e STAMP="$stamp" db sh -c \
      'pg_restore -U "$POSTGRES_USER" -d "${POSTGRES_DB}_restore_${STAMP}" --no-owner --single-transaction --exit-on-error' \
      < "$file" || restore_rc=$?
  fi
  if [[ $restore_rc != 0 ]]; then
    "${DC[@]}" exec -T -e STAMP="$stamp" db sh -c \
      'dropdb -U "$POSTGRES_USER" --if-exists "${POSTGRES_DB}_restore_${STAMP}"' || true
  else
    # Swap in one transaction. Writers are stopped; any remaining session is disconnected.
    "${DC[@]}" exec -T -e STAMP="$stamp" db sh -c '
      set -e
      psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -q -o /dev/null \
        -v live="$POSTGRES_DB" -v old="${POSTGRES_DB}_before_restore_${STAMP}" \
        -v new="${POSTGRES_DB}_restore_${STAMP}" <<"SQL"
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = :'"'"'live'"'"' AND pid <> pg_backend_pid();
BEGIN;
ALTER DATABASE :"live" RENAME TO :"old";
ALTER DATABASE :"new" RENAME TO :"live";
COMMIT;
SQL
      echo "restore: previous database kept as ${POSTGRES_DB}_before_restore_${STAMP} (drop it once no longer needed)"' \
      || restore_rc=$?
    if [[ $restore_rc != 0 ]]; then
      "${DC[@]}" exec -T -e STAMP="$stamp" db sh -c \
        'dropdb -U "$POSTGRES_USER" --if-exists "${POSTGRES_DB}_restore_${STAMP}"' || true
    fi
  fi
fi

if [[ $start == 0 ]]; then
  if [[ $restore_rc -ne 0 ]]; then
    echo "restore: FAILED (rc=$restore_rc); database unchanged; frontend, api and worker left stopped" >&2
    exit 1
  fi
  echo "restored $file (services left stopped)"
  exit 0
fi

# Recovery: bring the services back regardless of the restore outcome.
if ! "${DC[@]}" up -d --wait --wait-timeout 180 api worker; then
  echo "restore: api/worker did not become healthy after restore (rc=$restore_rc)" >&2
  exit 3
fi
publication_after="$(api_publication)"
if [[ $publication_after != "$publication_before" ]]; then
  echo "restore: API port publication changed ($publication_before -> $publication_after);" \
       "check COMPOSE_FILE (production must include compose.prod.yaml)" >&2
  exit 3
fi

if [[ $restore_rc -ne 0 ]]; then
  echo "restore: FAILED (pg_restore rc=$restore_rc); transaction rolled back, database unchanged," \
       "services restarted" >&2
  exit 1
fi
echo "restored $file"
