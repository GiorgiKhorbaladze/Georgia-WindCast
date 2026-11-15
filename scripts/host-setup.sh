#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu 24.04 host (Oracle Cloud Ampere A1, linux/arm64, or any
# amd64 VM) for Georgia WindCast. Idempotent: safe to run again.
#
#   sudo scripts/host-setup.sh [deploy-user]        (default deploy user: the sudo caller, else "ubuntu")
#
# What it does (nothing else):
#   1. Installs Docker Engine + Compose plugin from Docker's official apt repository.
#   2. Sets default container log rotation (json-file, 10 MB x 3).
#   3. Opens TCP 80/443 and UDP 443 in the host firewall (Oracle's Ubuntu images reject inbound
#      traffic except SSH by default) and persists the rules. The cloud security list / NSG must
#      also allow these ports; that is a console step (docs/DEPLOY-ORACLE.md).
#   4. Enables unattended security upgrades.
#   5. Installs a daily backup timer (systemd) that runs scripts/backup-rotate.sh as the deploy user.
# It never creates cloud resources, never changes billing, and never opens PostgreSQL or the API.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run with sudo" >&2; exit 1; fi
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_USER="${1:-${SUDO_USER:-ubuntu}}"
id "$DEPLOY_USER" >/dev/null 2>&1 || { echo "user $DEPLOY_USER does not exist" >&2; exit 1; }
. /etc/os-release
echo "host: $PRETTY_NAME, arch: $(uname -m), app dir: $APP_DIR, deploy user: $DEPLOY_USER"
[[ $ID == ubuntu ]] || echo "WARNING: tested on Ubuntu 24.04 only" >&2

step() { printf '\n== %s\n' "$*"; }

step "Docker Engine and Compose plugin (official repository)"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
docker --version
docker compose version
usermod -aG docker "$DEPLOY_USER"

step "Default container log rotation"
if [[ ! -s /etc/docker/daemon.json ]]; then
  cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
  systemctl restart docker
fi
systemctl enable --now docker >/dev/null

step "Host firewall: allow 80/tcp, 443/tcp, 443/udp (HTTP/3)"
open_port() {  # open_port <proto> <port>
  iptables -C INPUT -p "$1" --dport "$2" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null ||
    iptables -I INPUT 1 -p "$1" --dport "$2" -m conntrack --ctstate NEW -j ACCEPT
}
open_port tcp 80
open_port tcp 443
open_port udp 443
if command -v netfilter-persistent >/dev/null; then
  netfilter-persistent save
else
  DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
  netfilter-persistent save
fi
iptables -S INPUT | grep -E -- '--dport (80|443)' || true

step "Unattended security upgrades"
DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

step "Daily database backup timer"
cat > /etc/systemd/system/windcast-backup.service <<UNIT
[Unit]
Description=Georgia WindCast database backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=$DEPLOY_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/scripts/backup-rotate.sh
UNIT
cat > /etc/systemd/system/windcast-backup.timer <<'UNIT'
[Unit]
Description=Daily Georgia WindCast database backup

[Timer]
OnCalendar=*-*-* 02:17:00
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now windcast-backup.timer
systemctl list-timers windcast-backup.timer --no-pager || true

step "Done"
cat <<EOF
Next (as $DEPLOY_USER, after logging out and in so the docker group applies):
  cd $APP_DIR && cp .env.example .env && chmod 600 .env   # then edit .env (see docs/DEPLOY-ORACLE.md)
  scripts/deploy.sh <git-sha-or-branch>
EOF
