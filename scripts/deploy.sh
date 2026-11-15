#!/usr/bin/env bash
# Deploy (or roll back to) an exact git revision on the host.
#
#   scripts/deploy.sh <git-ref>         e.g. a commit SHA (recommended), a tag, or origin/main
#   scripts/deploy.sh --rollback        redeploy the revision that was live before the current one
#
# Steps: fetch -> check out the exact commit (detached) -> build images natively, tagged with the
# short SHA (DEPLOY_SKIP_BUILD=1: use images already tagged so) -> back up the database (if it is running) -> start with `docker compose up --wait`
# (migrations run first via the one-shot "migrate" service) -> verify health through the public
# edge -> record the revision in deploy/history.log.
#
# Uses COMPOSE_FILE from .env, so the production and public overlays always apply. Nothing is
# rolled back automatically: if verification fails the script stops and prints the rollback
# command. Rolling back across a schema migration also needs the pre-deploy backup it printed
# (scripts/restore.sh <file>); see docs/DEPLOY-ORACLE.md section "Updates and rollback".
set -euo pipefail
cd "$(dirname "$0")/.."
# `git checkout` below replaces this file while bash may still be reading it: run from a copy.
if [[ -z ${WINDCAST_DEPLOY_COPY:-} ]]; then
  copy="$(mktemp)"
  cp "$0" "$copy"
  WINDCAST_DEPLOY_COPY=1 WINDCAST_APP_DIR="$PWD" exec bash "$copy" "$@"
fi
cd "${WINDCAST_APP_DIR:-.}"
# shellcheck source=lib/compose.sh
source scripts/lib/compose.sh

die() { echo "ERROR: $*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }
env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
env_set() {  # env_set KEY VALUE  (in place; keeps the file mode)
  if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi
}

[[ -f .env ]] || die ".env missing: cp .env.example .env and fill it in (docs/DEPLOY-ORACLE.md)"
[[ $(stat -c %a .env) =~ ^6[04]0$ ]] || echo "WARNING: chmod 600 .env (it holds the database password)" >&2
grep -qE '^[A-Z_]+=change-me' .env && die ".env still contains change-me placeholders"
files="$(compose_files)"
[[ $files == *compose.prod.yaml* ]] || die "COMPOSE_FILE in .env must include compose.prod.yaml"
public=0
[[ $files == *compose.public.yaml* ]] && public=1
if [[ $public == 1 ]]; then
  site_cfg="$(env_get WINDCAST_SITE_ADDRESS)"
  url_cfg="$(env_get WINDCAST_PUBLIC_URL)"
  [[ -n $site_cfg ]] || die "WINDCAST_SITE_ADDRESS is empty"
  [[ $url_cfg == "https://$site_cfg" ]] ||
    die "WINDCAST_PUBLIC_URL must be https://$site_cfg (link previews and canonical URLs use it)"
fi

mkdir -p deploy
history=deploy/history.log
ref="${1:-}"
if [[ $ref == --rollback ]]; then
  [[ -s $history ]] || die "no deployment history"
  current="$(git rev-parse HEAD)"
  ref="$(awk -v cur="$current" '$2 != cur {prev=$2} END {print prev}' "$history")"
  [[ -n $ref ]] || die "no earlier revision in $history"
  echo "rolling back to $ref"
fi
[[ -n $ref ]] || die "usage: scripts/deploy.sh <git-ref> | --rollback"

step "Fetching and checking out $ref"
git fetch --quiet origin
sha="$(git rev-parse --verify "$ref^{commit}")" || die "unknown revision $ref"
if ! git diff --quiet || ! git diff --cached --quiet; then die "working tree has local changes"; fi
git checkout --quiet --detach "$sha"
tag="${sha:0:12}"
echo "revision: $sha (image tag $tag)"

env_set WINDCAST_IMAGE_TAG "$tag"
if [[ ${DEPLOY_SKIP_BUILD:-0} == 1 ]]; then
  # Images built elsewhere (or for a rehearsal) must already carry the tag of this exact commit.
  step "Using prebuilt images tagged $tag"
  for img in windcast-backend windcast-frontend windcast-caddy; do
    [[ $img == windcast-caddy && $public == 0 ]] && continue
    docker image inspect "$img:$tag" >/dev/null || die "image $img:$tag not found"
  done
else
  step "Building images natively for $(uname -m)"
  "${DC[@]}" build
fi

step "Pre-deploy backup"
if "${DC[@]}" ps --status running --services 2>/dev/null | grep -qx db; then
  backup="$(scripts/backup.sh backups)"
  echo "backup: $backup  (restore with: scripts/restore.sh $backup)"
else
  echo "database not running yet (first deployment): no backup needed"
fi

step "Starting the stack (migrations first)"
"${DC[@]}" up -d --wait --wait-timeout 300 --remove-orphans

step "Verifying"
[[ $(api_publication) == unpublished ]] || die "the API port is published: check COMPOSE_FILE"
site="$(env_get WINDCAST_SITE_ADDRESS)"
if [[ $public == 1 && -n $site ]]; then
  # DEPLOY_TLS_INSECURE=1 only for rehearsals with Let's Encrypt staging or Caddy's internal CA.
  curl_tls=()
  [[ ${DEPLOY_TLS_INSECURE:-0} == 1 ]] && curl_tls=(-k)
  ok=0
  for _ in $(seq 1 60); do
    if curl -fsS "${curl_tls[@]}" --max-time 10 "https://$site/healthz" >/dev/null 2>&1; then ok=1; break; fi
    sleep 5
  done
  [[ $ok == 1 ]] || die "https://$site/healthz did not answer. Check: docker compose logs caddy. Roll back: scripts/deploy.sh --rollback"
  curl -fsS "${curl_tls[@]}" --max-time 10 "https://$site/api/data/status" | head -c 300; echo
  echo "public edge OK: https://$site"
else
  "${DC[@]}" exec -T frontend wget -qO- http://127.0.0.1:3000/healthz
  echo
fi

printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sha" "$tag" >> "$history"
step "Deployed $sha"
docker system df --format 'table {{.Type}}\t{{.Size}}\t{{.Reclaimable}}' || true
echo "Old images can be removed with: docker image prune -a --filter 'until=720h'"
