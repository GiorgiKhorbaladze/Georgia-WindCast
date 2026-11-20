# Operations runbook: Streamlit edition (public pilot)

Scope: `https://georgia-windcast.streamlit.app` (Streamlit Community Cloud, deploys `main`), the
collector workflow `.github/workflows/collect-gse.yml` and the `data` branch. The older Docker stack
is covered by `docs/OPERATIONS.md`.

## 1. Components and normal behaviour

| Component | Normal |
|---|---|
| External trigger | cron-job.org job `8897487` POSTs `workflow_dispatch` for `collect-gse.yml` at :00/:15/:30/:45 (HTTP 204). Verified: 98 runs in 24 h, gaps 14.7-15.3 min, 0 missed (20.11.2026). |
| GitHub schedule | Backup cron `7,22,37,52 * * * *`. Best effort; fired 3 times in the same 24 h. |
| Collector run | About 20-60 s. Writes `gse/YYYY/MM/*.csv`, `balance/...`, `weather/...` and `status/gse_collector.json` to `data`, one commit per run. `concurrency: collect-gse` queues runs, never in parallel. |
| Freshness | `status.latest_label_utc` 3-18 min behind now. The app's "fresh" threshold is 10 min, so "stale" briefly between runs is expected. |
| App | Reads `data` (contents/raw), fills the minutes since the last run live from GSE (at most 4 requests per 3 min, last hour only), reads weather from Open-Meteo, with the stored copy as fallback. |

## 2. Daily or ad-hoc health check (read-only)

```bash
R=GiorgiKhorbaladze/Georgia-WindCast
# freshness (contents API bypasses the raw CDN cache)
gh api "repos/$R/contents/status/gse_collector.json?ref=data" --jq .content | base64 -d | jq '{latest_label_utc,last_success_at,last_run}'
# trigger cadence: event, time and result of the last runs
gh api "repos/$R/actions/workflows/collect-gse.yml/runs?per_page=10" --jq '.workflow_runs[]|[.event,.created_at,.conclusion]|@tsv'
```

Healthy: latest label under 20 min old, `failures: 0`, `integrity_error: null`, runs every 15 min
with event `workflow_dispatch`.

## 3. Failure modes and recovery

| Symptom | Likely cause | Action |
|---|---|---|
| No `workflow_dispatch` runs for more than 20 min | cron-job.org job disabled or failing, or token expired/revoked (HTTP 401/403 in cron-job.org history) | Check the cron-job.org history. On 401: create a new fine-grained token (this repository only, Actions read/write) and update the job's Authorization header. **Never paste the token into Issues, chat or the repository.** Until fixed, run *Actions → Collect GSE wind data → Run workflow* manually; the GitHub schedule continues best effort. |
| Runs succeed but `latest_label_utc` does not advance | GSE not publishing (404s, `not_published` > 0) or GSE site down | Nothing to fix locally. Gaps are recorded, rechecked (1/6/24/72 h) and never filled. Recent gaps are recovered automatically by the 12-96 h window. |
| Run fails with `failures > 0` | GSE 5xx or timeouts | Transient: the next run retries. If persistent for more than 2 h, check GSE availability. Deep backfill and gap repair pause automatically while failures occur. |
| `integrity_error` set, exit code 1 | A stored CSV or status file failed strict validation | **Stop and investigate. Do not delete files.** Inspect the last `data` commit (`git show <sha>`); if a bad write is confirmed, revert that single commit on `data` (`git revert <sha>`, pushed to `data`), then re-run the workflow. |
| Exit code 2 (stale) | No new label for more than `WINDCAST_ALERT_AFTER_HOURS` (6 h) | Treat as a GSE outage or trigger failure (rows above). |
| App shows old texts or names after a merge | Streamlit kept old modules | Fixed by the reload guard (PRs #29, #45). If it ever recurs: Streamlit Cloud → Manage app → Reboot. |
| App error page | Python exception in the latest `main` | Roll back (section 4). Check the Streamlit Cloud logs (Manage app → logs). |
| Weather panels "collector copy" or unavailable | Open-Meteo 429 (shared IP daily limit) or outage | Automatic fallback to the stored copy; no action. |

## 4. Rollback

- **App code:** create a revert PR for the offending merge commit (`git revert -m 1 <merge-sha>` on a
  branch), let CI pass, then merge with owner approval. Streamlit redeploys `main` automatically.
  Emergency (owner account): point the app at a known-good branch in Streamlit Cloud's app settings, or
  push the revert first; check the Community Cloud documentation for the current options.
- **Collector code:** same as app code. Data written by the bad version stays on `data`; revert
  individual `data` commits only if they are confirmed bad.
- **Data branch:** history-preserving `git revert` only; **never force-push `data`**. Every row
  carries `payload_sha256`, `parser_version` and `revision`, so any value can be traced to its
  source file.
- **Trigger:** to stop collection, disable cron-job.org job `8897487` (owner account). The GitHub
  schedule can be disabled under *Actions → Collect GSE wind data → ⋯ → Disable workflow*.

## 5. Secrets

- The only secret outside GitHub is the cron-job.org fine-grained token: this repository only,
  Actions read/write. cron-job.org execution details show URL, status and timing, not request
  headers (owner's screenshot of the execution details, 19.11.2026).
- The workflow uses the built-in `GITHUB_TOKEN` (`contents: write` for the collector job only).
- Scans (20.11.2026): no token pattern in tracked files, branch history since 17.11, Issues/PRs or
  recent run logs. Repeat after any incident.

## 6. Escalation and decisions

- Data/collector/backend: Claude Code lane (Issue #18). Map UI: Issue #49.
- The owner decides merges, deployments, cron/token changes, new data sources and publication of
  line-level data (see `docs/sources/rights.md`).
