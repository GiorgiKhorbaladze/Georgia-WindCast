# Security report - hardening work package (issue #18)

Date: 2026-11-15/16. Base: `main` = `33dd519` (PR #19 merged). The scans below ran on the hardening branch. The exact head and CI run IDs are recorded on the pull request. Threat model: [THREAT-MODEL.md](THREAT-MODEL.md).

**A passing scan is not production security approval.** These are static scans plus a dynamic scan of an ephemeral localhost stack. The real host, TLS certificate, OCI network and live traffic have not been tested.

## 1. Tools, versions, provenance

| Tool | Version | Provenance check | Data leaves the runner? |
| --- | --- | --- | --- |
| Trivy | 0.76.2 | SHA-256 pinned **and** cosign `verify-blob` against `https://github.com/aquasecurity/trivy/.github/workflows/reusable-release.yaml@refs/tags/v0.76.2` (Rekor entry 2026-11-05). Chosen after reviewing [GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23) (CVE-2026-33634: malicious v0.69.4, force-pushed `trivy-action`/`setup-trivy` tags). This repository uses **neither action**, only the verified binary. | Downloads the vulnerability DB only |
| cosign | 3.1.4 | SHA-256 from its release | No |
| TruffleHog | 3.99.9 | SHA-256 pinned | No (`--no-verification`: candidates are never sent to provider APIs; raw output is deleted, only a redacted report is kept) |
| Semgrep OSS | 1.185.0 (PyPI) + `semgrep/semgrep-rules` @ `a5ad171` + `.semgrep/windcast.yml` | Version and rules commit pinned | No (no login, `--metrics=off`; semgrep.dev is not contacted) |
| Nuclei (local only) | 3.11.1 + `nuclei-templates` v10.5.2 | SHA-256 from its release | Interactsh **off** (`-ni`), update check off. Target: an ephemeral `https://localhost` stack only (owner-approved) |
| ESLint rules | in repository | - | No |
| `/security-review` (Claude Code) | - | Its sub-agent stopped on an API rate limit; the same review was done inline on the diff (finding S9 below) | - |
| Cloudflare security-audit skill | `cloudflare/security-audit-skill` @ `c1c8a8c` | **Not installed.** NVIDIA SkillSpector (`c816150`, static mode `--no-llm`) reported 10 HIGH / 3 MEDIUM / 1 LOW pattern hits. On inspection they were mostly references to its own Node validator scripts and sub-agent prompts, but the policy is no installation of executable skills with unresolved HIGH flags. Only its domain headings were used as a checklist for the threat model. | No |
| Not used | PyRIT, ClamAV, Blind LLM agents: no project-specific requirement. Strix: needs an LLM provider key and sends application data to it; not authorised. Codex Security: skipped by owner decision (cost/access). | - | - |

## 2. Findings

Severity is the project-specific risk after triage, not the raw scanner label.

| ID | Severity | Where | Evidence | Status |
| --- | --- | --- | --- | --- |
| S1 | **High** | Base images (python 3.12.12, node 22.21.1/alpine 3.22, postgres 17.7) | Trivy: fixable **CRITICAL** OpenSSL (CVE-2026-31789) in frontend and postgres; backend 7 CRITICAL / 120 HIGH; postgres 3 CRITICAL / 53 HIGH | **Fixed**: python 3.12.16, node 22.23.5/alpine 3.24, postgres 17.12, all pinned by digest |
| S2 | **High** | backend runtime image | Trivy CRITICAL GHSA-hq85-5cpj-mr62 in `uv` 0.11.32, a build-only tool shipped at runtime | **Fixed**: multi-stage build, runtime holds only the venv |
| S3 | **High** | postgres image | CRITICAL CVE-2025-68121 + 25 HIGH in `gosu` (Go 1.24.6 stdlib); container started as root with 5 capabilities | **Fixed**: `deploy/postgres` runs as `postgres`, gosu removed, **zero capabilities**, read-only root |
| S4 | Medium | frontend runtime image | HIGH in global npm (brace-expansion, picomatch, pacote, sigstore, ip-address); not in the application lockfile | **Fixed**: npm/npx/corepack/yarn removed from runtime |
| S5 | Medium | Caddy image | Trivy DS-0002 (runs as root); HIGH CVE-2026-78661 `golang.org/x/net` 0.60 | **Fixed**: non-root (uid 10002), sysctl for low ports, `cap_drop: ALL`; x/net replaced with 0.62.0. While fixing this, a file capability on the official binary made exec fail without capabilities ("operation not permitted"); the binary is now rewritten without it |
| S6 | Medium | `.github/workflows/*` | Semgrep: 29 action references by mutable tag (the Trivy incident class); `actions/checkout` persisted the job token | **Fixed**: all pinned to commit SHAs, `persist-credentials: false` |
| S7 | Medium | Containers / network | Default bridge network: the edge could reach the API and DB, the API had internet access; containers kept default capabilities and writable roots | **Fixed**: segmented networks, `cap_drop: ALL`, `no-new-privileges`, read-only roots. Tested in the edge smoke |
| S8 | Medium | Docker builds | OS updates **silently skipped**: `apt-get update` and `apk upgrade` failures were ignored (`&&`-list under `set -e`, unchecked exit codes). Found while verifying S1 here | **Fixed**: `apt-get update --error-on=any` and `set -e` with separate statements; the explicit `OS_UPDATES=0` is for restricted networks only |
| S9 | Low | `scripts/security/scan.sh` (new tooling) | A TruffleHog crash would have read as "0 findings" (`|| true`) | **Fixed**: scanner errors return rc=2 (tested with a failing stub) |
| S10 | Low | `WindMap.tsx` | Semgrep ERROR `insecure-innerhtml` + `dangerouslySetInnerHTML` ×2. **Not exploitable**: only numbers reached the sink | **Fixed** (defence in depth): DOM/JSX only; ESLint now forbids HTML sinks, `eval`, `document.write`; `arrowRotation` test with an XSS payload |
| S11 | Low | language cookie | Missing `HttpOnly`/`Secure` (value already allow-listed) | **Fixed**: HttpOnly, SameSite=Lax, Secure on https; E2E test |
| S12 | Info | headers (Nuclei) | Missing COOP / X-Permitted-Cross-Domain-Policies | **Fixed**. COEP/CORP deliberately not set: they would break cross-origin map tiles and Open Graph hotlinking |

**Triaged false positives (not changed):**
- Semgrep `use-defused-xml` in `gse_parser.py`: the import is a type hint only. Suppressed inline with justification; the XXE/bomb regression test proves defusedxml refuses both.
- Semgrep `missing-image-version` (×6): `FROM ${ARG}`, whose defaults are digest-pinned.
- Semgrep `html-in-template-string`: a local brand-asset script with constant input.
- Semgrep `len-all-count`: a performance note.
- TruffleHog "Alchemy" ×19: the local, git-ignored `.mypy_cache`, never committed; full git history (33 commits, 9 branches) has **0** findings.
- Nuclei `jan-detect`: a generic `/healthz` JSON match.

**No findings:** dependency vulnerabilities in `backend/uv.lock` and `frontend/package-lock.json` (Trivy, fixable HIGH/CRITICAL = 0); SQL built from strings; SSRF (no user-controlled URLs); TLS verification disabled; `shell=True`.

## 3. Image results after the fixes (Trivy 0.76.2, amd64)

| Image | Before | After |
| --- | --- | --- |
| postgres | 3 CRITICAL / 53 HIGH | **0 findings** |
| backend | 7 CRITICAL / 120 HIGH | **0 CRITICAL**; 49 HIGH, of which 2 (zlib) have a Debian fix that the strict `apt-get upgrade` applies in CI (this sandbox could not reach the Debian mirror) |
| frontend | 5 CRITICAL / 60 HIGH | **1 MEDIUM** |
| caddy | 2 HIGH | 1 HIGH without an upstream fix (`go-jose` v3.0.5, DoS via crafted RSA parameter; reachable only through ACME/JWS handling with Let's Encrypt) |

The arm64 images are scanned with the same gate in the CI job **ARM64 images**.

## 4. Runtime verification (ephemeral localhost stack, all three overlays)

The edge smoke, in CI and locally, asserts:
- only Caddy publishes ports;
- HTTP redirects to HTTPS;
- HSTS/CSP/nosniff/COOP headers are present and server banners absent;
- internal paths answer 404;
- the public status endpoint is allow-listed;
- 429 with `Retry-After` beyond the limit;
- generic outage page and recovery;
- **caddy ✗→ api:8000, caddy ✗→ db:5432, frontend ✗→ db:5432, api ✗→ internet, frontend ✓→ api**;
- caddy/frontend/api/worker/db run non-root with `CapEff=0000000000000000` and read-only roots.

The Compose smoke and the rollback rehearsal pass on the hardened stack, including atomic and exact restores with a capability-free database. The load and cancellation regressions (connection-pool safety) remain in the backend tests.

Nuclei dynamic scan (all HTTP templates, info and above): 7 informational results, 0 low/medium/high/critical.

## 5. CI gates and triage process

| Gate (release blocker) | Job |
| --- | --- |
| Any secret candidate in history or tree | Security / Secrets |
| Any Semgrep ERROR (community rules + `.semgrep/windcast.yml` invariants: defusedxml-only parsing, no SQL string building, TLS verification on, no `shell=True`, public routes use `publicError`/`toPublicStatus`) | Security / SAST |
| Fixable HIGH/CRITICAL in lockfiles; HIGH/CRITICAL misconfig; any secret | Security / Trivy |
| Fixable CRITICAL in any production image (amd64 and arm64) | Security / Trivy, CI / ARM64 images |
| HTML sinks, `eval`, `document.write` in frontend code | CI / Frontend (ESLint) |
| Network segmentation and least privilege | CI / Public edge smoke |

**Triage:** every finding is classed as *confirmed*, *candidate* or *false positive* against the actual code.
- A false positive is suppressed only inline (`# nosemgrep` plus a reason on the line above) or, for Trivy, in a future `.trivyignore` entry with the advisory, the reason and an expiry date, in a reviewed PR.
- Candidates stay open in the PR or issue until proven either way.
- HIGH findings without an available fix are reported, not gated, and re-checked by the weekly scheduled run.

**Cost:** about 10-15 runner minutes per Security run (image builds dominate), plus about 1 minute added to the ARM64 job. This fits the GitHub Free private-repository allowance (2,000 minutes per month) at the current PR rate. No paid service is used.

## 6. Remaining risks and release blockers

- Not security-tested yet: the real OCI host, its security list and firewall, the Let's Encrypt certificate (and a TLS scan), real client IP handling at the edge, and native arm64. **These block a public launch**, together with the owner gates in [PUBLIC-LAUNCH-CHECKLIST.md](../PUBLIC-LAUNCH-CHECKLIST.md).
- CSP still contains `'unsafe-inline'` (Next.js bootstrap). A nonce-based CSP is recommended as a follow-up (low; no HTML sinks exist).
- Upstream data integrity relies on TLS plus validation; a compromised source could still serve plausible values (see the threat model).
- Remaining HIGH findings without upstream fixes (Debian packages, `go-jose` in Caddy) stay on the weekly watch.
