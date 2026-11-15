#!/usr/bin/env bash
# Atomic restore of a backup produced by scripts/backup.sh into the running Compose stack.
#
# 1. Validates the archive (pg_restore --list) before anything is touched.
# 2. Stops api and worker (the only writers).
# 3. Restores in ONE transaction (--single-transaction --exit-on-error): any error rolls the whole
#    restore back, so the database is either fully restored or left exactly as it was.
# 4. Always restarts api and worker, on success AND on failure, with the same Compose
#    configuration as startup (COMPOSE_FILE), and verifies the API port publication is unchanged.
#
# Exit codes: 0 restored; 1 restore failed and was rolled back (services running, data unchanged);
#             2 archive invalid (nothing changed); 3 services did not come back healthy.
# Usage: scripts/restore.sh <file.dump>
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=lib/compose.sh
source scripts/lib/compose.sh
file="${1:?usage: scripts/restore.sh <file.dump>}"
test -s "$file" || { echo "restore: $file is missing or empty; nothing changed" >&2; exit 2; }

echo "restore: compose files: $(compose_files || true)"
if ! "${DC[@]}" exec -T db pg_restore --list < "$file" > /dev/null 2>&1; then
  echo "restore: $file is not a valid pg_dump archive; nothing changed" >&2
  exit 2
fi
publication_before="$(api_publication)"

"${DC[@]}" stop api worker
restore_rc=0
"${DC[@]}" exec -T db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction --exit-on-error' \
  < "$file" || restore_rc=$?

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
