# Shared Compose invocation for startup, backup, restore and rollback.
#
# Every script uses plain `docker compose`, which reads COMPOSE_FILE and COMPOSE_PROJECT_NAME from
# the environment or from .env. A production host sets, in .env:
#     COMPOSE_FILE=compose.yaml:compose.prod.yaml
# so that every command, including restore and rollback, applies the production overlay and the
# API is never republished. See docs/OPERATIONS.md section 1.
DC=(docker compose)

compose_files() {
  echo "${COMPOSE_FILE:-$(grep -E '^COMPOSE_FILE=' .env 2>/dev/null | cut -d= -f2- || true)}"
}

# Prints "published" or "unpublished" for the API container's port 8000, from the container's
# actual port publishers (`docker compose port` prints ":0" with exit 0 when unpublished).
api_publication() {
  "${DC[@]}" ps --format json api 2>/dev/null | python3 -c '
import json, sys
rows = [json.loads(line) for line in sys.stdin.read().splitlines() if line.strip()]
if len(rows) == 1 and isinstance(rows[0], list):
    rows = rows[0]
published = any(p.get("PublishedPort", 0) for r in rows for p in (r.get("Publishers") or []))
print("published" if published else "unpublished")'
}
