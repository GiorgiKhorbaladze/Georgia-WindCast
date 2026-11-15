# Public launch checklist

Issue #18. The site is **not** public. This list keeps engineering status separate from external restrictions and owner decisions. Do not tick a box without evidence. Status as of 2026-11-15.

## A. Engineering (Claude)

| Item | Status | Evidence |
| --- | --- | --- |
| Integrated release candidate with the #16 corrections and re-reviews | Done, not merged | PR #17 (head `e3961da`, CI green) |
| GE/EN page titles and descriptions, Open Graph and Twitter/LinkedIn preview tags, original 1200×630 social card | Done | `e2e/public.spec.ts`; `frontend/design/og-card.html` → `public/og-image.png` |
| Favicon, SVG icon, Apple touch icon, web manifest | Done | same spec checks they are served |
| Canonical URLs only when an approved `WINDCAST_PUBLIC_URL` (https origin) is set | Done | `src/lib/site.ts` + unit tests; edge smoke checks the canonical tag |
| `noindex` + `robots.txt` disallow + empty sitemap until `WINDCAST_PUBLIC_INDEXING=true` | Done | `e2e/public.spec.ts`, edge smoke |
| Independence notice (footer + About), privacy note, non-operational disclaimer | Done | About page; spec checks the text |
| Accessible mobile navigation (disclosure menu, Escape, focus return) | Done | `e2e/public.spec.ts` (mobile) + axe checks on all pages |
| Gap labels on history charts no longer overlap | Done | `labelFlags` unit tests |
| Public status endpoint allow-listed (no error text, backoff, counters, environment) | Done | `publicStatus.test.ts`, E2E, edge smoke |
| Generic public error codes; long query parameters rejected | Done | `publicStatus.test.ts`, E2E |
| HTTPS with automatic certificates and renewal; HTTP→HTTPS redirect; HSTS | Done (Caddy) | edge smoke with Caddy's internal CA; Let's Encrypt itself is untested until a public host exists |
| Only 80/443 published; API, PostgreSQL and frontend unpublished; internal paths 404 at the edge | Done | edge smoke |
| Per-IP rate limits (defaults: data 600/min, pages 1200/min, so an office behind one NAT address is not blocked; static assets exempt), 429 with `Retry-After`; configurable | Done | edge smoke (run with low limits) |
| Security headers (CSP, nosniff, frame-ancestors, referrer, permissions; no server banner) | Done | E2E + edge smoke |
| Restart policies, memory limits, log rotation | Done | `compose.prod.yaml`, `compose.public.yaml` |
| linux/arm64 images and a full-stack smoke on arm64 (emulated) | Done | CI job **ARM64 images** |
| Anonymous-traffic load check | Done locally | [evidence/public/load-test.md](evidence/public/load-test.md) |
| Host setup, deploy and backup-rotation scripts; runbook | Done | `scripts/host-setup.sh`, `scripts/deploy.sh`, `scripts/backup-rotate.sh`, [DEPLOY-ORACLE.md](DEPLOY-ORACLE.md) |
| Coordinated cross-schema rollback (paired backup, exact restore, no newer migration on recovery) | Done | `scripts/rollback.sh`; `scripts/rollback-rehearsal.sh` + CI job (incompatible and broken migrations) |
| Real deployment, real certificate, external-device test, TLS scan, LinkedIn unfurl test | **Blocked** | needs section D item 2 |
| Safari/iPhone and Firefox checks | **Open** | CI covers Chromium desktop and Pixel 7 emulation only |

## B. Provider restrictions

| Provider | Restriction | Handling |
| --- | --- | --- |
| OCI Always Free | 2 OCPU / 12 GB A1 (2026 reduction), 200 GB storage, 10 TB egress; capacity not guaranteed; idle instances may be reclaimed | Sized to fit ([DEPLOY-ORACLE.md](DEPLOY-ORACLE.md) §2); no artificial load; off-host backups and a rebuild runbook |
| Let's Encrypt | Per registered domain rate limits | DuckDNS subdomain (`duckdns.org` is on the PSL); staging CA for rehearsals |
| OpenFreeMap tiles | Free public tile service, attribution required | Attribution shown; browser loads tiles directly (stated in the privacy note) |
| GitHub Actions (private repository) | Free minutes quota; the ARM64 job uses emulation and takes longer | Monitor usage; the job can be limited to release branches if minutes run short |

## C. Data permissions (external)

| Source | Status | Gate |
| --- | --- | --- |
| GSE 3-minute XML exports | **No documented permission** for automated retrieval, storage and public redistribution; ACT/NRE meanings unconfirmed | `WINDCAST_GSE_INGESTION_ENABLED=false` until written confirmation. Draft request (unsent) in #18 |
| Open-Meteo free API | The coordinator's reading of https://open-meteo.com/en/terms in #18: the free API is for non-commercial use, and promotional activities count as commercial. Promotion through a professional LinkedIn profile may therefore not qualify. (Claude could not open that page from the build environment.) | `WINDCAST_WEATHER_INGESTION_ENABLED=false` until written clarification or a compliant alternative. No advertising, subscriptions or tracking may be added without review |

If either feed stays disabled, the site shows that state explicitly ("disabled", "unavailable"). It never shows invented values.

## D. Owner decisions and actions

1. Merge approval for PR #17, then for the #18 PR (after independent review).
2. OCI account, card verification, instance and security-list rules ([DEPLOY-ORACLE.md](DEPLOY-ORACLE.md) §3); DuckDNS subdomain (§4); read-only deploy key (§5).
3. GSE and Open-Meteo permissions (section C).
4. Explicit authorisation to open the site to the public and set `WINDCAST_PUBLIC_INDEXING=true`.
5. LinkedIn announcement (drafts in #18), only after a verified public URL exists and the screenshots used show real, timestamped data states.

## E. Definition of "publicly launched"

All of section A done on the merged head with green CI; section C cleared for every enabled feed; the HTTPS URL opened from an external device on mobile and desktop; real, authorised data retrieval shown with correct freshness; backups and monitoring working; and the owner's explicit go-ahead. Until then the status is **code complete, not deployed**.
