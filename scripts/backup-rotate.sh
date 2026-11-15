#!/usr/bin/env bash
# Daily backup with local retention, for the systemd timer installed by scripts/host-setup.sh.
#   scripts/backup-rotate.sh          keeps the newest BACKUP_KEEP (default 14) archives in ./backups
# Host-only settings go in .backup.env (git-ignored, sourced by bash; not read by Compose):
#   BACKUP_KEEP=14
#   BACKUP_COPY_CMD='rclone copy "$1" remote:windcast-backups'   # receives the archive as $1
# The copy command and its credentials live only on the host. Without one, the operator must copy
# backups off the host.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
[[ -f .backup.env ]] && source .backup.env
keep="${BACKUP_KEEP:-14}"
copy_cmd="${BACKUP_COPY_CMD:-}"

file="$(scripts/backup.sh backups)"
echo "backup written: $file ($(du -h "$file" | cut -f1))"

# Retention: newest $keep archives stay, older ones are deleted.
mapfile -t old < <(ls -1t backups/windcast-*.dump 2>/dev/null | tail -n +"$((keep + 1))")
for f in "${old[@]}"; do rm -f -- "$f" && echo "pruned: $f"; done

if [[ -n $copy_cmd ]]; then
  bash -c "$copy_cmd" _ "$file"
  echo "off-host copy done"
else
  echo "NOTE: no BACKUP_COPY_CMD configured; copy backups off this host regularly." >&2
fi
df -h . | tail -1
