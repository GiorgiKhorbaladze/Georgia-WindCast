#!/usr/bin/env bash
# Restore a backup produced by scripts/backup.sh into the running Compose stack.
# Stops api and worker during the restore, then starts them again.
# Usage: scripts/restore.sh <file.dump>
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:?usage: scripts/restore.sh <file.dump>}"
test -s "$file"
docker compose stop api worker
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$file"
docker compose up -d --wait api worker
echo "restored $file"
