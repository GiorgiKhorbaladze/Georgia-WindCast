#!/usr/bin/env bash
# Public-edge smoke test (issue #18) with all three overlays:
#   compose.yaml + compose.prod.yaml + compose.public.yaml
# Caddy serves "localhost" with its internal CA (no Let's Encrypt contact). Checks:
#   - only Caddy publishes host ports (80/443); frontend, API and PostgreSQL publish none
#   - HTTP redirects to HTTPS; HTTPS serves the app with HSTS and the app's security headers
#   - internal API paths are not routed; the public status contract is allow-listed
#   - per-IP rate limiting answers 429 on the data routes
#   - generic error page when the frontend is down, recovery when it returns
#
# Runs in an isolated Compose project with a random database password; needs host ports 80/443.
# Usage: scripts/edge-smoke.sh            (SMOKE_SKIP_BUILD=1 to reuse images, KEEP_STACK=1 to keep)
#        WINDCAST_IMAGE_TAG=arm64 ...      to test images built for another architecture
set -euo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME="${SMOKE_PROJECT_NAME:-windcast-edge}"
export COMPOSE_FILE="compose.yaml:compose.prod.yaml:compose.public.yaml${SMOKE_EXTRA_COMPOSE:+:$SMOKE_EXTRA_COMPOSE}"
export POSTGRES_USER=windcast POSTGRES_DB=windcast
POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export POSTGRES_PASSWORD
export WINDCAST_SITE_ADDRESS=localhost ACME_EMAIL=smoke@example.invalid
export WINDCAST_PUBLIC_URL=https://localhost
export WINDCAST_WORKER_HEARTBEAT_SECONDS=2
# Low limits so the rate-limit check needs few requests (production defaults: 600 / 1200 per min).
export WINDCAST_RATE_DATA_PER_MIN=60 WINDCAST_RATE_PAGES_PER_MIN=240
# shellcheck source=lib/compose.sh
source scripts/lib/compose.sh

H="https://localhost"
CURL=(curl -sS --max-time 10 -k)
step() { printf '\n== %s\n' "$*"; }
fail() { echo "FAIL: $*" >&2; dump_diagnostics; exit 1; }

cleanup() {
  if [[ ${KEEP_STACK:-0} != 1 ]]; then
    step "Tearing down (volumes removed)"
    "${DC[@]}" down -v --remove-orphans
  fi
}
trap cleanup EXIT

wait_https() {  # wait_https <path> <seconds> <expected-substring>
  local body
  for ((i = 0; i < $2; i++)); do
    if body=$("${CURL[@]}" -f "$H$1" 2>/dev/null) && [[ $body == *"$3"* ]]; then
      printf '%s' "$body"
      return 0
    fi
    sleep 1
  done
  fail "timeout waiting for $1"
}

published_services() {
  "${DC[@]}" ps --format json 2>/dev/null | python3 -c '
import json, sys
rows = [json.loads(l) for l in sys.stdin.read().splitlines() if l.strip()]
if len(rows) == 1 and isinstance(rows[0], list):
    rows = rows[0]
out = sorted({"%s:%s" % (r["Service"], p["PublishedPort"]) for r in rows for p in (r.get("Publishers") or []) if p.get("PublishedPort")})
print(" ".join(out))'
}

step "Starting the public stack (project: $COMPOSE_PROJECT_NAME)"
"${DC[@]}" config --quiet
"${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
build_flag=(--build)
[[ ${SMOKE_SKIP_BUILD:-0} == 1 ]] && build_flag=()
if ! "${DC[@]}" up "${build_flag[@]}" -d --wait --wait-timeout 300; then
  dump_diagnostics
  exit 1
fi

step "Only Caddy publishes host ports"
pub=$(published_services)
echo "published: $pub"
[[ $pub == "caddy:443 caddy:80" ]] || fail "unexpected published ports: $pub"

step "HTTP redirects to HTTPS"
loc=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost/map)
echo "$loc"
[[ $loc == "308 https://localhost/map" ]] || fail "no HTTPS redirect"

step "HTTPS serves the dashboard with security headers"
wait_https / 90 'GEORGIA WINDCAST' >/dev/null
headers=$("${CURL[@]}" -D - -o /dev/null "$H/")
grep -qi '^strict-transport-security: max-age=31536000' <<<"$headers" || fail "HSTS missing"
grep -qi "^content-security-policy:.*frame-ancestors 'none'" <<<"$headers" || fail "CSP missing"
grep -qi '^x-content-type-options: nosniff' <<<"$headers" || fail "nosniff missing"
if grep -qi -E '^(server|x-powered-by):' <<<"$headers"; then fail "server banner exposed"; fi
echo "headers OK"
html=$("${CURL[@]}" "$H/")
grep -q '<link rel="canonical" href="https://localhost"' <<<"$html" || fail "canonical URL missing"
grep -q 'content="noindex, nofollow"' <<<"$html" || fail "public pilot must be noindex by default"
echo "canonical and noindex OK"

step "Internal paths are not routed"
for p in /api/v1/status /api/health /docs /openapi.json; do
  code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$H$p")
  echo "$p -> $code"
  [[ $code == 404 ]] || fail "$p is reachable ($code)"
done

step "Public status exposes only allow-listed fields"
status=$(wait_https /api/data/status 60 '"worker"')
python3 - "$status" <<'PY'
import json, sys
s = json.loads(sys.argv[1])
assert sorted(s) == ["generated_at", "sites", "sources", "worker"], sorted(s)
for src in s["sources"]:
    assert sorted(src) == ["id", "last_success_at", "state"], sorted(src)
print("status contract OK:", [x["id"] for x in s["sources"]])
PY

step "Rate limit on data routes (configured 60/min per IP for this test)"
codes=$(for _ in $(seq 1 75); do "${CURL[@]}" -o /dev/null -w '%{http_code}\n' "$H/api/data/generation-latest"; done | sort | uniq -c)
echo "$codes"
grep -q ' 429$' <<<"$codes" || fail "no 429 after 75 requests"
retry=$("${CURL[@]}" -D - -o /dev/null "$H/api/data/generation-latest" | grep -i '^retry-after:' || true)
echo "${retry:-no Retry-After header}"
code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$H/about")
[[ $code == 200 ]] || fail "pages zone should be independent of the data zone ($code)"
echo "pages still served while data routes are limited"

step "Frontend outage: generic error, then recovery"
"${DC[@]}" stop frontend
body=$("${CURL[@]}" -w ' [%{http_code}]' "$H/history" || true)
echo "$body"
[[ $body == *"Service temporarily unavailable."*"[502]" ]] || fail "unexpected outage response"
if ! "${DC[@]}" up -d --wait --wait-timeout 120 frontend; then dump_diagnostics; exit 1; fi
wait_https /history 60 'GEORGIA WINDCAST' >/dev/null
echo "recovered"

step "EDGE SMOKE PASSED"
