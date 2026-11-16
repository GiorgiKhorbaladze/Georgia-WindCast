# Georgia WindCast - threat model

Scope: the production architecture in `compose.yaml` + `compose.prod.yaml` + `compose.public.yaml` on one host (OCI A1, [DEPLOY-ORACLE.md](../DEPLOY-ORACLE.md)), the GitHub repository and its Actions. Status: 2026-11-16, security work package for issue #18. Companion: [SECURITY-REPORT.md](SECURITY-REPORT.md).

## 1. What must be protected

| Asset | Why it matters | Primary threat |
| --- | --- | --- |
| **Integrity of published data**: source timestamps, GSE quality flags, freshness/stale/unavailable states, forecast run/coverage provenance | The site's value is that it never shows invented, stale-as-fresh or mislabelled values | Manipulated or malformed source data; logic regressions; cache serving stale data as current |
| Collected GSE history (PostgreSQL) | Cannot be re-fetched (GSE archive is irregular) | Loss, corruption, unsafe restore/rollback |
| Availability of the public site | Public, LinkedIn-linked | Traffic bursts, abusive clients, resource exhaustion |
| Host and containers | One VM runs everything | Container escape amplification, lateral movement |
| Deployment and repository credentials (deploy key, `.env`, GitHub Actions tokens) | Control over code and data | Supply-chain compromise, leaked secrets |
| Visitors | Anonymous; only a language cookie | XSS, clickjacking, tracking |

## 2. Trust boundaries and data flows

```
Internet visitors ──HTTPS──► Caddy (edge net) ──► frontend (edge+app) ──► api (app+data) ──► db (data)
GSE XML / Open-Meteo JSON ◄──HTTPS── worker (data+egress) ──► db
GitHub (code, Actions) ──► host via read-only deploy key + scripts/deploy.sh (operator)
```

1. **Internet → Caddy.** Only ports 80/443 are published. TLS termination, HSTS, per-IP rate limits, internal paths answer 404, generic error pages.
2. **Caddy → frontend.** Plain HTTP on the private `edge` network. Caddy cannot reach the API or the database (network segmentation, tested).
3. **Frontend → API.** `app` network (internal). The browser never talks to the API: only `/api/data/*` route handlers with allow-listed output and generic errors.
4. **Worker → upstream sources.** The only container with outbound internet (`egress`). Upstream data is **untrusted input**: strict parsers, value bounds, label checks.
5. **API/worker/migrate → database.** `data` network (internal); the database runs as non-root with no capabilities.
6. **GitHub → host.** The operator deploys exact SHAs. CI has read-only `contents` permission and pinned, SHA-referenced actions.

## 3. Threats and controls (STRIDE-style, project-specific)

| # | Threat | Existing / added control | Evidence |
| --- | --- | --- | --- |
| T1 | **Spoofed or malformed GSE XML** (wrong period, future label, entity bombs, XXE, non-finite or out-of-range values) | defusedxml (entities forbidden), embedded label must equal the requested period, future labels rejected, values bounded -50..2000 MW, quality code stored verbatim and non-ACT shown as unverified | `tests/test_gse_*`, new XXE/bomb test; Semgrep rule `windcast-python-unsafe-xml-parse` |
| T2 | **Manipulated Open-Meteo data** (run changes mid-fetch, gaps, wrong units) | Run time checked before/after fetch; contiguous per-site, per-height coverage; mixed-run provenance; never presented as measurement | `tests/test_weather_*` |
| T3 | **Stale data shown as current** (frontend cache, open tabs) | 5 s coalescing cache, failures never cached; freshness computed from the source label; `fresh_until` expiry in the open page | `api.test.ts`, `freshness.spec.ts` |
| T4 | **XSS** | React escaping; **no raw-HTML sinks** (innerHTML/dangerouslySetInnerHTML removed); ESLint forbids sinks and eval; CSP `default-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'` | ESLint rules; `wind.test.ts` (`arrowRotation` refuses non-numbers) |
| T5 | **Clickjacking / cross-origin abuse** | `frame-ancestors 'none'`, `X-Frame-Options: DENY`, COOP `same-origin` | `public.spec.ts`, edge smoke |
| T6 | **Information disclosure** (errors, operational status, server banners) | Allow-listed public status; generic error codes; Server/X-Powered-By removed; full diagnostics host-only | `publicStatus.test.ts`, edge smoke |
| T7 | **SSRF** | No user-controlled URL anywhere: upstream base URLs come from configuration, site IDs from a fixed allow-list | code review; Semgrep |
| T8 | **SQL injection** | SQLAlchemy expressions / bound parameters only | Semgrep rule `windcast-python-sql-string-building` |
| T9 | **Denial of service / pool exhaustion** | Per-IP rate limits; request coalescing; sessions closed in-thread; pool timeout 5 s; API-local statement and idle-transaction timeouts; bounded query ranges (≤ 31 days) and parameter length | `test_connection_safety.py`, load test |
| T10 | **Container compromise → lateral movement** | All containers non-root, `cap_drop: ALL`, `no-new-privileges`, read-only root filesystems; DB never root (gosu removed); network segmentation (edge cannot reach API/DB, API has no internet) | edge smoke "Network segmentation" + "Least privilege" |
| T11 | **Supply chain**: images, dependencies, CI actions, scanners | Base images pinned by **digest**; OS updates fail closed; uv/npm removed from runtime images; lockfiles (`uv.lock`, `package-lock.json`) scanned; actions pinned to commit SHAs; `persist-credentials: false`; scanners pinned by SHA-256, Trivy cosign-verified (post GHSA-69fq-xp46-6x23) | `scripts/security/install-tools.sh`, Trivy gates |
| T12 | **Leaked credentials** | No secrets in code (`.env` git-ignored, mode 600 checked by `deploy.sh`); TruffleHog over full history, values never printed or sent out | secrets gate |
| T13 | **Unsafe recovery** (restore/rollback reapplying migrations, partial restore) | Atomic restore; exact-restore rollback paired with backups; no newer code started during recovery | rollback rehearsal (CI) |
| T14 | **Tracking / privacy** | No analytics; one HttpOnly, SameSite=Lax, Secure (on https) language cookie with an allow-listed value; size-capped logs | `public.spec.ts` cookie test |

## 4. Accepted / residual risks

- **CSP allows `'unsafe-inline'` scripts and styles** (Next.js inline bootstrap). Impact is limited because no HTML sink exists and React escapes output. A nonce-based CSP is possible (all pages are dynamic) and is recommended as a follow-up.
- **Single host:** no high availability; mitigated by backups, the rebuild runbook and rate limits.
- **IPv6 and per-IP limits:** behind Docker's userland proxy, IPv6 clients share one limit. The host must stay IPv4-only unless Docker IPv6 is configured.
- **Upstream integrity is not authenticated** beyond TLS: a compromised GSE or Open-Meteo endpoint could serve plausible but false values within the validated bounds. Values are always attributed and labelled; they are not certified.
- **Base images without upstream fixes:** remaining HIGH findings without an available fix (e.g. Debian packages, `go-jose` in Caddy) are tracked in [SECURITY-REPORT.md](SECURITY-REPORT.md) and re-checked weekly by the scheduled security workflow.
