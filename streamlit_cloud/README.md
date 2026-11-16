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

**Recovery limits:** each run requests missing periods within the last 12 h, subject to the request budget. A longer interruption can leave older gaps even if the source still retains those files; use an explicit backfill (up to 48 h). Retention was observed on 2026-11-16 and is not a provider guarantee. After four 404 responses a missing period is abandoned (except the newest due period), so late publication can also leave gaps. No gap-free continuity is guaranteed.

**Source revisions:** each run reserves at most 20 requests and one quarter of its request budget to revalidate stored periods within the lookback, prioritising non-ACT and recent records. Each period is rechecked at most hourly. Corrected bytes update the record and revision counter; identical bytes do not. Corrections outside the window or beyond the bounded budget may remain undiscovered.

**Freshness between runs:** the app still checks the newest GSE periods live (at most 4 requests per 3 minutes for all visitors, last hour only) and merges them with the durable rows. Each row keeps its source label, quality code and SHA-256.

**Open-Meteo second path:** Open-Meteo limits free use per IP address (10,000 requests/day). Cloud hosts share egress IPs, and during testing this project's environment received `429 Daily API request limit exceeded` from the archive API. The collector therefore also stores the validated raw forecast once per new model run (run time checked before and after the download) and ERA5 once per day under `weather/`. The app uses the stored copy when its own request fails or when the stored run is newer, and labels it "collector copy". The same strict parser and time-axis checks apply to both paths. New manifests reference immutable SHA-256-addressed payloads; readers verify the raw-byte digest and aware, non-future timestamps before adoption. Legacy mutable copies also require a matching digest. Invalid or missing copies retain the last validated product independently.

### Data branch format

`gse/YYYY/MM/YYYY-MM-DD.csv` (UTC date of the label):

```
period_label_utc,period_label_local,value_mw,quality,retrieved_at_utc,payload_sha256,parser_version,revision
```

`weather/forecast.json`, `weather/era5.json` (raw Open-Meteo payloads) with `*_meta.json` (run, retrieval time, URL, SHA-256) and `weather/status.json`.

`status/gse_collector.json` holds the last run, last successful acquisition, latest label, revalidation times and pending 404 retries. The app shows the last successful acquisition and warns if no source reading is newer than 6 h, including all-404 outages.

### Failure behaviour

| Event | Behaviour |
| --- | --- |
| GSE outage | Run records the failure; history keeps the last rows; the workflow fails (email to the owner) only when no reading is newer than 6 h |
| Schema drift, label mismatch, future label | Invalid records are refused; valid records from the same run may be saved; the workflow fails visibly |
| GitHub skips scheduled runs | Next run backfills only 12 h by default; longer stops can leave gaps; manual recovery up to 48 h is bounded and not guaranteed |
| Scheduled workflow disabled (60 days inactivity) | The app warns that the collector is stale; re-enable in Actions |
| Open-Meteo `429` (shared cloud IPs) | Last good forecast is kept with its run and retrieval time, and the status degrades to stale or unavailable; retries back off |

## Deploy on Community Cloud (owner, about 5 minutes)

1. <https://share.streamlit.io> → sign in with GitHub.
2. **Create app** → repository `GiorgiKhorbaladze/Georgia-WindCast`, branch `main` (after PR #21 is merged; before that, `work/streamlit-cloud`), main file `streamlit_cloud/app.py`, **Advanced settings → Python 3.12**, custom subdomain `georgia-windcast`.
3. No secrets are required. Optional environment-style settings: `WINDCAST_USER_AGENT` (identifying User-Agent for GSE/Open-Meteo) and `WINDCAST_DATA_BASE_URL` (defaults to this repository's `data` branch).

The collector starts automatically once `.github/workflows/collect-gse.yml` is on `main` (scheduled workflows run only from the default branch). A one-off backfill of up to 48 h can be started from *Actions → Collect GSE wind data → Run workflow*.

## Limits that remain

- GitHub cron is best effort: runs can be delayed by tens of minutes or skipped. The live check covers the newest hour, and the bounded 12 h backfill can recover some missed runs.
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
