# ADR 0003 - Zero-cost public hosting: OCI Always Free A1 first, Cloudflare as a fallback study

Status: proposed (issue #18). It needs coordinator review and an owner decision; nothing has been provisioned.

## Context

The owner wants a public HTTPS URL, shareable on LinkedIn, with no mandatory recurring hosting fees, while the repository stays private. The working stack has five parts: a Next.js frontend, a FastAPI API, PostgreSQL, a Python ingestion worker polling every 60 s, and a scheduler that keeps history. It must keep collecting real data and storing history. A static or fake frontend is not acceptable.

## Decision

1. **Primary: one OCI Always Free Ampere A1 VM running the existing Docker Compose stack**, with Caddy in front for HTTPS and rate limiting (`compose.public.yaml`, [DEPLOY-ORACLE.md](../DEPLOY-ORACLE.md)). No code is rewritten, and every existing test and operational procedure (backup, atomic restore, rollback) applies unchanged.
2. **Free hostname: DuckDNS** (`<name>.duckdns.org`, on the Public Suffix List). `sslip.io`/`nip.io` were rejected: they are not on the Public Suffix List (checked 2026-11-15), so all their users share one Let's Encrypt rate-limit bucket. Certificate issuance there could fail without warning.
3. **Cloudflare is not adopted now.** It is documented below as a fallback that would need a port and its own review.

## Option assessment

| Criterion | OCI A1 + Compose | Cloudflare Pages + Workers + D1 (free) |
| --- | --- | --- |
| Runs the existing code | Yes, unchanged | No. The API, worker and SQL would need a rewrite in TypeScript for Workers, with PostgreSQL replaced by SQLite (D1). Pages alone cannot run Python, PostgreSQL or a worker. |
| Ingestion every 60 s | Worker loop | Cron Triggers (1-minute minimum, 5 per account on Free). The GSE XML parsing and backoff logic would need re-implementing. |
| History storage | PostgreSQL on a 50 GB volume | D1 Free: 5 GB total, 5 M rows read per day, 100 k rows written per day; queries stop when a quota is exceeded. A 30-day history view reads about 14,400 GSE rows, so a few hundred such views a day would exhaust the read quota. |
| Request limits | VM capacity only | Workers Free: 100,000 requests per day, 10 ms CPU per invocation, 128 MB memory |
| Operational risk | Idle reclamation, capacity, a single VM | Quotas exhausted under a LinkedIn traffic spike would leave the site unavailable for the rest of the day |
| Verified here | arm64 builds and full smoke under emulation | Not prototyped |

Cloudflare limits as reported by the coordinator in #18 from developers.cloudflare.com (Workers limits, D1 pricing, Pages limits). Re-check them before any port.

## Consequences

- One VM is a single point of failure. Daily off-host backups and a rebuild runbook are the mitigation.
- The owner performs the account, card-verification and console steps. Claude prepared everything that does not need them.
- If OCI is unavailable (no capacity, account refused), the next step is to **ask the owner**. Options at that point: another free VM offer that meets the same terms, or a reviewed Cloudflare port with feature-parity tests. The project does not switch silently.
- Cloudflare Tunnel could later front the OCI VM (no inbound ports, origin IP hidden). Named tunnels need a domain on Cloudflare, so it is not part of the free-hostname path.
