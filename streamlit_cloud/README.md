# Georgia WindCast - Streamlit Community Cloud edition

Public, zero-cost edition of Georgia WindCast. The original Next.js/FastAPI/PostgreSQL stack is unchanged and remains the full-featured fallback ([docs/DEPLOY-ORACLE.md](../docs/DEPLOY-ORACLE.md)). The owner selected Community Cloud, a public repository, public deployment and GSE/Open-Meteo use (owner-reported authorization, Issue #18).

## What it shows

| Page | Content |
| --- | --- |
| Overview | Latest GSE national wind aggregate (MW, 3-minute average) with source time, quality code and freshness; last 24 h chart; map of the three verified sites with model wind at 80 m |
| Forecast | DWD ICON (Open-Meteo) speed and direction at 10/80/120/180 m; model run, retrieval time, valid-time range and continuous forward coverage (≤ 72 h) |
| History | 24 h / 7 d / 30 d generation history from the durable store, with gaps; CSV download (UTC); ERA5 reanalysis (10/100 m, 7 days with a 5-day lag) |
| About data | Sources, methodology, limitations, independence, hosting and attribution |

Georgian and English. Display times are Asia/Tbilisi; stored data is UTC. Production parsers and rules from `backend/app` are reused unchanged: strict defusedxml GSE parser, embedded-label validation, strict Open-Meteo parser, verified site list. Freshness follows the production API: age from the source label first (stale after 10 min), then quality (non-`ACT` = unverified, value still shown). Model wind is never presented as measured wind or as a generation forecast. No value is interpolated or invented; missing periods are gaps.

## Persistence (why and how)

Community Cloud has no persistent storage, and apps sleep after 12 h without visitors, so the app itself cannot collect continuously. Options compared on 2026-11-16:

| Option | Durability | Cadence | Free-tier limits / risks | Accounts needed | Verdict |
| --- | --- | --- | --- | --- | --- |
| In-memory cache in the app (previous pilot) | Lost on restart/sleep | Only while a page is open | - | none | Not acceptable as history |
| **GitHub Actions collector → `data` branch (chosen)** | Git history on GitHub | Scheduled every 15 min; GitHub may delay or skip runs | Public repo: Actions minutes free. Scheduled workflows run only from the default branch and are disabled after 60 days without repository activity. Repo growth about 15-20 MB/year of CSV (compresses well) | none (existing repo) | **Chosen**: no new account, no secret, transparent public data, easy recovery |
| Free managed Postgres (e.g. Neon, Supabase) | Good | Needs its own collector anyway | Quotas, project pausing on inactivity, terms change; credentials in Streamlit/GitHub secrets | new owner account + secrets | Viable later; not needed now |
| Actions artifacts / caches | Expire (≤ 90 days / evicted) | - | - | none | Rejected |

**Why gaps do not appear when GitHub delays runs:** GSE keeps published 3-minute files for at least 48 h (checked 2026-11-16: files 1, 3, 6, 12, 24 and 48 h old all answered 200). Every collector run backfills all missing periods of the last 12 h, newest first. One successful run per 12 h therefore gives a complete record. A period GSE never published stays a gap: after 4 runs with 404 it is no longer requested.

**Freshness between runs:** the app still checks the newest GSE periods live (at most 4 requests per 3 minutes for all visitors, last hour only) and merges them with the durable rows. Each row keeps its source label, quality code and SHA-256.

### Data branch format

`gse/YYYY/MM/YYYY-MM-DD.csv` (UTC date of the label):

```
period_label_utc,period_label_local,value_mw,quality,retrieved_at_utc,payload_sha256,parser_version,revision
```

`status/gse_collector.json` holds the last run, last success, latest label and pending 404 retries. The app shows the collector's last success and warns when it is older than 6 h.

### Failure behaviour

| Event | Behaviour |
| --- | --- |
| GSE outage | Run records the failure; history keeps the last rows; the workflow fails (email to the owner) only when no reading is newer than 6 h |
| Schema drift, label mismatch, future label | Nothing is written; the workflow fails visibly |
| GitHub skips scheduled runs | Next run backfills 12 h; beyond 48 h GSE retention is irregular, so a longer stop can leave gaps |
| Scheduled workflow disabled (60 days inactivity) | The app warns that the collector is stale; re-enable in Actions |
| Open-Meteo `429` (shared cloud IPs) | Last good forecast is kept with its run and retrieval time, and the status degrades to stale or unavailable; retries back off |

## Deploy on Community Cloud (owner, about 5 minutes)

1. <https://share.streamlit.io> → sign in with GitHub.
2. **Create app** → repository `GiorgiKhorbaladze/Georgia-WindCast`, branch `main` (after PR #21 is merged; before that, `work/streamlit-cloud`), main file `streamlit_cloud/app.py`, **Advanced settings → Python 3.12**, custom subdomain `georgia-windcast`.
3. No secrets are required. Optional environment-style settings: `WINDCAST_USER_AGENT` (identifying User-Agent for GSE/Open-Meteo) and `WINDCAST_DATA_BASE_URL` (defaults to this repository's `data` branch).

The collector starts automatically once `.github/workflows/collect-gse.yml` is on `main` (scheduled workflows run only from the default branch). A one-off backfill of up to 48 h can be started from *Actions → Collect GSE wind data → Run workflow*.

## Limits that remain

- GitHub cron is best effort: runs can be delayed by tens of minutes or skipped. The live check covers the newest hour, and the 12 h backfill covers missed runs.
- History starts when collection starts (plus up to 48 h of backfill). There is no older archive.
- Link previews (LinkedIn, Open Graph) use Streamlit's generic page metadata; Community Cloud does not allow custom meta tags.
- Edge protection (TLS, rate limiting) is provided by Streamlit's hosting, not by the Caddy configuration of the main stack.
- Safari/iOS were not tested on real devices; layout was checked in Chromium desktop and Pixel 7 emulation.

## Verify locally

```
python -m pip install -r streamlit_cloud/requirements.txt -r streamlit_cloud/collector-requirements.txt pytest==8.4.2
python -m pytest streamlit_cloud/tests -q          # offline: recorded payloads, fixed clock
streamlit run streamlit_cloud/app.py
python streamlit_cloud/collector.py --data-dir /tmp/windcast-data --lookback-hours 1   # live, ~20 requests
```
