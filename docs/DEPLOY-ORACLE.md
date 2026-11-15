# Public deployment on Oracle Cloud Always Free (Ampere A1)

Issue #18. This runbook takes Georgia WindCast from a merged commit to a public HTTPS URL on one Oracle Cloud Infrastructure (OCI) Always Free Ampere A1 instance. The stack and its Docker Compose files stay unchanged. **Nothing here has been run against a real OCI tenancy yet:** account creation, card verification, quotas and capacity are external steps only the owner can take (section 9).

| | |
| --- | --- |
| Architecture | One VM: Caddy (HTTPS, rate limits) → Next.js frontend → FastAPI API → PostgreSQL, plus the ingestion worker. Only Caddy publishes ports (80/443). |
| Compose files | `compose.yaml` + `compose.prod.yaml` + `compose.public.yaml`, set once through `COMPOSE_FILE` in `.env` |
| Free hostname | `<name>.duckdns.org`. `duckdns.org` is on the Public Suffix List, so each subdomain has its own Let's Encrypt limits. A purchased domain works the same way. |
| Recurring cost | None, provided that only Always Free resources are used and the account stays on the Free Tier (section 2). |

## 1. Why OCI A1, and what was verified

| Check | Result | Evidence |
| --- | --- | --- |
| All base images publish `linux/arm64` | Yes: `postgres:17.7-alpine3.22`, `python:3.12.12-slim`, `node:22.21.1-alpine3.22`, `caddy:2.11.9-(builder-)alpine` | Image manifests checked 2026-11-15 |
| Backend image builds for arm64 (all Python wheels available) | Yes, in about 1 min | Local buildx run plus CI job **ARM64 images** |
| Frontend image builds for arm64 (Next.js standalone, Node 22) | Yes | Same |
| Caddy with the rate-limit module builds for arm64 | Yes. The build cross-compiles with Go, so it needs no emulation | Same |
| Full stack runs on arm64: migrations, production overlay, failing and successful restore, public edge | Yes, under QEMU emulation. The overlay `deploy/emulation.yaml` only relaxes healthcheck timeouts for the slower emulation. | `scripts/compose-smoke.sh` and `scripts/edge-smoke.sh` with `WINDCAST_IMAGE_TAG=arm64`, locally and in CI |
| Runs on real Ampere hardware | **Not yet.** It will be verified on the first deployment. | - |

**Sizing.** The memory limits in `compose.prod.yaml`/`compose.public.yaml` add up to about 2.7 GB (db 1 GB, api 512 MB, worker 384 MB, frontend 512 MB, Caddy 256 MB). That fits comfortably in a 2 OCPU / 12 GB A1 shape, and a 1 OCPU / 6 GB shape would also do. Images take about 1.2 GB. Database growth with both feeds enabled is estimated at well under 1 GB per year: about 480 GSE rows per day, plus the forecast/reanalysis rows for 3 sites (an estimate, not a measurement). A 50 GB boot volume is plenty.

## 2. Always Free limits that matter (re-check before provisioning)

Oracle's Always Free terms change. In particular, the Ampere allowance was reduced in 2026, from 4 OCPU/24 GB to 2 OCPU/12 GB. **The owner must check the live page before creating anything:** https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm (that host could not be fetched from the build environment, so the figures below come from the coordinator's reading of that page in #18 and from 2026 press reports).

| Resource | Always Free allowance as last reported | WindCast use |
| --- | --- | --- |
| Ampere A1 compute | 1,500 OCPU-hours and 9,000 GB-hours per month (= 2 OCPU / 12 GB running continuously) | 1 instance, ≤ 2 OCPU / ≤ 12 GB |
| Block storage (boot + block volumes) | 200 GB total | 50 GB boot volume |
| Outbound data transfer | 10 TB per month | Far below; each page view is a few hundred KB |
| Public IPv4 | Ephemeral public IP with the instance | 1 |

**Risks and how to handle them honestly:**
- **Idle reclamation.** Oracle may reclaim Always Free instances that it considers idle over 7 days (low CPU, network and memory utilisation). WindCast is a light workload and may look idle. Do **not** run artificial load to avoid this: the directive forbids it, and it would misrepresent usage. Mitigation: daily backups copied off the host (section 6) and this runbook, which rebuilds a host in well under an hour. Upgrading to a Pay As You Go account is reported to exempt instances from idle reclamation; verify this on Oracle's page. Upgrading is an owner decision, because Pay As You Go accounts *can* incur charges for anything outside Always Free.
- **Capacity.** Ampere capacity in the home region is not guaranteed ("Out of host capacity"). Retry later, or try another availability domain in the same region. The home region cannot be changed after sign-up.
- **Trial credits.** New accounts get time-limited trial credits. A resource created during the trial is **not** free merely because it is covered by the trial. Create only shapes marked "Always Free-eligible".
- **Account inactivity.** Keep the account in use (sign in occasionally). Third-party reports mention suspension of abandoned free accounts; Oracle's own wording should be checked.

## 3. Owner steps in the OCI console (one time)

1. Sign up at https://signup.cloud.oracle.com/. A payment card is used for identity verification. Choose a home region with Ampere availability; a nearby EU region suits Georgian visitors.
2. **Create instance**: image *Canonical Ubuntu 24.04* (aarch64); shape *VM.Standard.A1.Flex*, 2 OCPU / 12 GB (or 1/6). Confirm the "Always Free-eligible" label. Boot volume 50 GB. Assign a public IPv4. Paste an SSH public key.
3. **Networking → Security list of the instance's subnet**: add ingress rules for TCP 80, TCP 443 and UDP 443 from `0.0.0.0/0`. Keep SSH (22) restricted to your own IP if possible. Add no other port: PostgreSQL and the API are never exposed.
4. Note the public IP.

## 4. Free hostname (DuckDNS)

1. Sign in at https://www.duckdns.org/, then create a subdomain, e.g. `windcast-ge`, and set its IP to the instance's public IP.
2. Check from any machine: `dig +short windcast-ge.duckdns.org` must print the instance IP.
3. Keep the DuckDNS token private. It is needed only if the IP changes later, in which case update the IP on the DuckDNS page.

Caddy then obtains a Let's Encrypt certificate automatically over HTTP-01 on port 80 and renews it before expiry. For a dry run without real certificates, set `ACME_CA` to Let's Encrypt staging first (section 5).

## 5. Install and first deployment (on the instance)

The repository is private, so the host needs read access. Use a **read-only deploy key** for this repository only (GitHub → repository Settings → Deploy keys → Add, *without* write access).

```bash
ssh ubuntu@<public-ip>
ssh-keygen -t ed25519 -f ~/.ssh/windcast_deploy -N ""      # add the .pub as a read-only deploy key
printf 'Host github.com\n  IdentityFile ~/.ssh/windcast_deploy\n' >> ~/.ssh/config
sudo mkdir -p /opt/windcast && sudo chown ubuntu: /opt/windcast
git clone git@github.com:GiorgiKhorbaladze/Georgia-WindCast.git /opt/windcast
cd /opt/windcast
sudo scripts/host-setup.sh ubuntu                           # Docker, firewall, upgrades, backup timer
exit                                                        # log in again so the docker group applies
```

Configure, then deploy:

```bash
cd /opt/windcast
cp .env.example .env && chmod 600 .env
openssl rand -hex 24                                        # paste as POSTGRES_PASSWORD
nano .env
```

| `.env` key | Value |
| --- | --- |
| `POSTGRES_PASSWORD` | the random value |
| `COMPOSE_FILE` | `compose.yaml:compose.prod.yaml:compose.public.yaml` |
| `WINDCAST_SITE_ADDRESS` | `windcast-ge.duckdns.org` |
| `ACME_EMAIL` | an address that receives certificate notices |
| `WINDCAST_PUBLIC_URL` | `https://windcast-ge.duckdns.org` |
| `WINDCAST_PUBLIC_INDEXING` | `false` until the owner authorises the public launch |
| `WINDCAST_GSE_INGESTION_ENABLED` / `WINDCAST_WEATHER_INGESTION_ENABLED` | `false` until the data permissions in [PUBLIC-LAUNCH-CHECKLIST.md](PUBLIC-LAUNCH-CHECKLIST.md) are cleared |

Optional dry run: `ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory`. Browsers then warn about the certificate, but issuance and renewal are proven. Remove the line and redeploy for real certificates.

```bash
scripts/deploy.sh <approved-commit-sha>
```

`deploy.sh` checks out the exact commit and builds natively on arm64. It backs up the database when one exists, starts the stack with migrations first and checks that the API is unpublished. It then waits for `https://<site>/healthz` and prints the public status. It records the revision in `deploy/history.log`.

## 6. Monitoring, backups, logs

- **Health:** `https://<site>/healthz` (frontend) and `https://<site>/api/data/status` (allow-listed source and worker states). Any free uptime monitor can poll these. On the host, `docker compose ps` shows all services healthy.
- **Diagnostics (host only):** `docker compose logs -f --tail=100 caddy frontend api worker`. The full source status, including last errors, is available on the host only ([OPERATIONS.md](OPERATIONS.md) §3).
- **Backups:** the `windcast-backup.timer` installed by `host-setup.sh` runs `scripts/backup-rotate.sh` daily and keeps the newest 14 archives in `/opt/windcast/backups`. **Copy backups off the host**, either automatically with `BACKUP_COPY_CMD` in `/opt/windcast/.backup.env` (e.g. an `rclone` remote, configured and authenticated on the host only) or manually with `scp ubuntu@<ip>:/opt/windcast/backups/*.dump .`. Test a restore occasionally: `scripts/restore.sh backups/<file>`. The restore is atomic, and a failed restore leaves the data unchanged ([OPERATIONS.md](OPERATIONS.md) §4).
- **Logs:** container logs rotate at 10 MB × 3–5 files per service. Caddy access logs (client IP, time, path) are kept only within that size limit, which matches the privacy note on the About page.
- **Disk:** `df -h /` and `docker system df`. Remove old images after successful upgrades with `docker image prune -a --filter until=720h`.

**Rate limits and client addresses.** Caddy limits requests per client IP: by default 600/min on data routes and 1200/min on pages, set by `WINDCAST_RATE_DATA_PER_MIN` and `WINDCAST_RATE_PAGES_PER_MIN` in `.env`. Docker preserves the real client address for **IPv4** traffic to published ports. For **IPv6**, unless Docker's own IPv6 support is configured, Docker's userland proxy forwards connections and every IPv6 visitor appears as the same internal address, so they would share one limit. Keep the instance IPv4-only (the OCI default) unless Docker IPv6 is set up and verified.

## 7. Updates and rollback

```bash
cd /opt/windcast
scripts/deploy.sh <new-approved-sha>      # backup, build, migrate, start, verify
scripts/rollback.sh                       # undo the last deployment attempt: old code + its database
```

**How a deployment is paired with its backup.** Before starting a new revision, `deploy.sh` takes a backup of the running database. That backup carries the schema of the revision being replaced. It records `<new sha> <previous sha> <backup>` in `deploy/last-attempt` before anything starts. Each successful deployment is also logged in `deploy/history.log`.

**What `rollback.sh` does.** It takes no arguments when undoing the last attempt, whether that attempt succeeded or failed. The order of steps is deliberate:

1. Resolves the previous revision and checks that its images are still on the host. It stops if they are missing and prints the rebuild command.
2. **Pairing check:** the backup's Alembic revision must equal the previous code's migration head. If not, it stops and **nothing is changed**; the newer stack keeps running.
3. Stops frontend, API and worker. The newer code's migrate, API and worker are **not started again**.
4. **Exact restore:** the backup is loaded into a fresh database. Only when that succeeds is it swapped in by renaming, in one transaction. Tables or columns created by the newer migration therefore cannot survive. The replaced database is kept as `windcast_before_restore_<UTC>` for salvage.
5. Checks out the previous revision, selects its image tag, and verifies that the database is at that code's head, so its migrate step has nothing to apply.
6. Starts the old stack and checks the following:
   - all services are healthy;
   - no migration ran (from the migrate log);
   - the API is still unpublished.

| Failure during rollback | State | What to do |
| --- | --- | --- |
| Pairing check or archive invalid | Nothing changed | Choose the right backup: `scripts/rollback.sh --to <sha> --backup <file>` |
| Restore into the fresh database fails | Live database unchanged; frontend, API and worker stopped | Fix the archive, or restart the newer stack with `docker compose up -d --wait` |
| Old stack does not start after the swap | Database = backup; previous database kept | Inspect `docker compose logs`; the kept database still holds the newer data |

**Data written after the backup** is not in the restored database. That includes GSE readings collected by the newer revision, and the content of any failed deployment. That data stays in the kept `windcast_before_restore_*` database. Drop kept databases when they are no longer needed: `docker compose exec db dropdb -U windcast <name>`.

**Failed deployment** (for example a broken migration): PostgreSQL runs the migration in one transaction, so a failure leaves the schema unchanged and `deploy.sh` stops, pointing to `scripts/rollback.sh`. It still records the attempt, so `rollback.sh` returns to the previous revision.

**Verified by** `scripts/rollback-rehearsal.sh`, locally and in the CI job *Rollback rehearsal*. The rehearsal works in a throwaway clone:

1. Deploys A (0003 schema) and writes a sentinel row.
2. Deploys B, an incompatible migration that adds a table and a column, and writes data.
3. Checks that a mismatched backup is refused with nothing changed.
4. Rolls back to A and checks:
   - the schema fingerprint is identical to A's;
   - Alembic is at 0003, the sentinel row is present and B's objects are gone;
   - A's images are running and healthy;
   - no migration ran and the database and API are unpublished.
5. Deploys C, a deliberately broken migration, which must fail.
6. Rolls back again with the same checks.

`scripts/restore.sh` on its own is for recovering data **within the same code version**. It restarts the current version, which applies that version's migrations.

**Disable a data feed immediately:** set `WINDCAST_GSE_INGESTION_ENABLED=false` (or the weather flag) in `.env`, then `docker compose up -d worker api`. The UI then reports the source as disabled. Stored history stays, and nothing is invented.

## 8. Rebuild after loss or reclamation

1. Create a new instance (section 3) and point DuckDNS at its IP (section 4).
2. Repeat section 5 with the same `.env` values (keep a copy of `.env` in a password manager).
3. `scripts/deploy.sh <sha>`, then `scripts/restore.sh <latest off-host backup>`.

GSE history that was never backed up cannot be re-fetched, because GSE's archive is irregular. This is why off-host backups matter.

## 9. External boundaries (owner only)

| Step | Who | Status |
| --- | --- | --- |
| OCI account, card verification, region choice | Owner | Not started |
| Create the instance and security-list rules | Owner (or Claude with console/API access the owner explicitly grants) | Not started |
| DuckDNS account and subdomain (or a purchased domain) | Owner | Not started |
| Read-only deploy key on the private repository | Owner | Not started |
| Data permissions (GSE, Open-Meteo) and opening to the public | Owner | Open ([PUBLIC-LAUNCH-CHECKLIST.md](PUBLIC-LAUNCH-CHECKLIST.md)) |

No resource has been created, no account accessed, no money spent.
