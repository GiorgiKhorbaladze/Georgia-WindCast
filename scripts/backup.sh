#!/usr/bin/env bash
# Logical backup of the WindCast database (pg_dump custom format) from the running Compose stack.
# Usage: scripts/backup.sh [output-dir]      (default: ./backups)
# Uses the same Compose configuration as startup (COMPOSE_FILE in .env or the environment).
# Restore with scripts/restore.sh <file>. Store backups off-host; they contain no secrets but
# do contain the collected history, which cannot be re-fetched from GSE.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=lib/compose.sh
source scripts/lib/compose.sh
out_dir="${1:-backups}"
mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="$out_dir/windcast-$stamp.dump"
"${DC[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$file"
test -s "$file"
# Verify the archive is readable before reporting success.
"${DC[@]}" exec -T db pg_restore --list < "$file" > /dev/null
echo "$file"
