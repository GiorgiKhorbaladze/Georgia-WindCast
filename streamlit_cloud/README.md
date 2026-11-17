# Georgia WindCast - Streamlit Community Cloud edition

Public, zero-cost edition of Georgia WindCast. The original Next.js/FastAPI/PostgreSQL stack is unchanged and remains the full-featured fallback ([docs/DEPLOY-ORACLE.md](../docs/DEPLOY-ORACLE.md)). The owner selected Community Cloud, a public repository, public deployment and GSE/Open-Meteo use (owner-reported authorization, Issue #18).

## What it shows

| Page | Content |
| --- | --- |
| Overview | Latest GSE national wind generation (MW, 3-minute average) with source time, quality code and freshness; energy today, yesterday and yesterday until the same time (MWh) with completeness; peaks; hourly profile today vs yesterday; last 24 h; map of the three verified sites with model wind at 80 m |
| Historical analysis | 24 h / 7 d / 30 d / 90 d / custom range; filters by hour window, quality code and complete days; statistics (total MWh, mean, median, min/max, standard deviation, missing periods, completeness); daily totals with 7-day rolling mean; daily/weekly/monthly tables; weekday pattern (from 14 complete days); distribution; filtered CSV (UTC); ERA5 reanalysis, labelled as model data |
| Forecast | Experimental national MW estimate with empirical band and held-out accuracy versus climatology and persistence; DWD ICON wind speed and direction at 10/80/120/180 m with run, valid time and continuous coverage |
| Forecast accuracy | Archived ICON runs scored by site, height and lead time (≤6 h ... 48-72 h): MAE, RMSE, bias, circular direction error, pair counts; reference = later short-range run or ERA5 at 10 m |
| Data and methodology | Collector health: last successful collection, latest stored period, completeness for 24 h and 7 d, missing intervals, recovered periods, search window, deep-backfill progress; sources, methodology, disclaimers |

Georgian and English, one vocabulary (`i18n.py`). Dark analytics theme (`ui.py`). Display times are Asia/Tbilisi; stored data is UTC. Official GSE values, model wind and the MW estimate carry distinct labels everywhere.

### Power system balance (`balance.py`)

The same GSE 3-minute file also carries total hydro, thermal, wind and solar generation, total generation and national consumption. The collector stores them in `balance/YYYY/MM/DATE.csv` with no extra requests, and the app shows:
- a separate stacked chart (sources plus derived net import/export, with consumption as a line) on the overview, for the last 24 h;
- a dedicated page with 24 h/48 h/7 d/30 d ranges, current values, generation mix, energy totals with completeness, generation profiles by hour of day, and CSV.

On the recorded file, hydro + thermal + wind + solar = total generation, and consumption − generation = the sum of all tie-line flows. The per-country tie-line sums are not used: the Russia sum read 0 while its individual lines carried 32.6 MW. Net interchange is therefore derived and labelled as derived. A balance refusal never blocks the wind record. Quality codes are kept per block; their meaning is unpublished.

### Energy and day conventions (`analytics.py`)

A GSE label marks the end of its 3-minute interval. Energy = sum of stored 3-minute averages × 0.05 h. A Tbilisi day holds labels 00:03 ... 24:00 (480 periods). Missing periods are counted, never filled; a day is "complete" at ≥ 99 % of its periods; today is always "in progress". Non-ACT periods are included in totals and counted separately. MW is power, MWh is energy.

### Experimental MW forecast (`mwmodel.py`)

- **Target:** hourly mean of the GSE national aggregate; an hour counts only with ≥ 16 of 20 periods.
- **Predictors:** ICON wind at 80 and 120 m at the three sites (speed, speed², speed³, capped at 30 m/s) and local hour (sin/cos). Training uses archived forecasts: the Open-Meteo historical forecast archive (stored daily by the collector) or, until that exists, the project's own short-lead archive. Neither contains measurements or future information.
- **Model:** ridge regression on standardized predictors, fixed regularization (no tuning on test data), numpy only.
- **Validation:** time-ordered split; the last 25 % of paired hours (≥ 24 h) are held out. Reported against climatology (training mean by hour) and persistence (value 1/6/24 h earlier) on the same hours.
- **Output:** the model refit on all paired hours is applied to the current ICON run for the next 48 h, clipped to the observed range (+10 %). The band shows the 10-90 % quantiles of held-out residuals (empirical, not a probabilistic guarantee).
- **Threshold:** no forecast is shown below 168 paired hours; the page states how many are available.
- **Skill label:** the page states whether the held-out MAE beats the best baseline available at a day-ahead lead (climatology or 24 h persistence). If it does not, a warning says the estimate is illustrative only. Persistence of 1 h and 6 h stays in the table but does not decide the label, because it is not available 24-48 h ahead.
- **Updates:** with every new model run (about every 6 h) and as GSE history grows.
- **Status:** independent experimental estimate. Not official GSE data, not per-plant output, not for operational or dispatch decisions.

### Wind direction (`compass.py`, `charts.py`)

- **Convention (one convention app-wide):** degrees say where the wind blows FROM, clockwise from north: 0°/360° from north, 90° from east, 180° from south, 270° from west. Text is shown next to the exact degrees, in 8 localized sectors (for example `270° - დასავლეთიდან` / `270° - from west`).
- **Chart:** speed and direction are two stacked panels on one time axis, so one hover shows both for the same hour. Direction is drawn as points only, because joining 359° to 1° with a line would suggest a 358° swing. Hours below 3 m/s get hollow markers (direction less informative). Missing hours stay gaps; values are not smoothed.
- **Map (`sitemap.py`):** one arrow per site from the 80 m ICON value of the current hour, pointing where the air moves (FROM + 180°); the card and tooltip give speed, FROM degrees with the Georgian/English sector, height and Tbilisi valid time. No interpolated wind field. A missing value gets no arrow and an "unavailable" text; light wind (< 3 m/s) gets a grey arrow. The arrow is an inline SVG icon (no external asset) with a constant on-screen size; its rotation follows deck.gl's counter-clockwise angle convention, checked visually.
- **Time axis:** Tbilisi time; ticks every 12 h on a 3-day forecast, with midnight labelled by its date. A dotted orange line labelled "now"/"ახლა" marks the current time.

### Forecast accuracy (`verification.py`)

No anemometer measurements exist at the sites. The archived runs are therefore compared with model-based references, and the page says so:
- the most recent later run at lead < 6 h (shares the model's biases);
- or ERA5 at 10 m (independent model, about 25 km, 5-day lag).

The reference is never taken from the run being scored. Direction errors are circular and use only hours with reference speed ≥ 3 m/s. Results accumulate as the archive grows (60 days of runs listed).

## Persistence (why and how)

Community Cloud has no persistent storage, and apps sleep after 12 h without visitors, so the app itself cannot collect continuously. Options compared on 2026-11-16:

| Option | Durability | Cadence | Free-tier limits / risks | Accounts needed | Verdict |
| --- | --- | --- | --- | --- | --- |
| In-memory cache in the app (previous pilot) | Lost on restart/sleep | Only while a page is open | - | none | Not acceptable as history |
| **GitHub Actions collector → `data` branch (chosen)** | Git history on GitHub | Scheduled every 15 min; GitHub may delay or skip runs | Public repo: Actions minutes free. Scheduled workflows run only from the default branch and are disabled after 60 days without repository activity. Repo growth about 15-20 MB/year of CSV (compresses well) | none (existing repo) | **Chosen**: no new account, no secret, transparent public data, easy recovery |
| Free managed Postgres (e.g. Neon, Supabase) | Good | Needs its own collector anyway | Quotas, project pausing on inactivity, terms change; credentials in Streamlit/GitHub secrets | new owner account + secrets | Viable later; not needed now |
| Actions artifacts / caches | Expire (≤ 90 days / evicted) | - | - | none | Rejected |

**Recovery limits:** each run requests missing periods within the last 12 h, subject to the request budget. A longer interruption can leave older gaps even if the source still retains those files; use an explicit backfill (up to 48 h). Retention was observed on 2026-11-16 and is not a provider guarantee. After four 404 responses a missing period is abandoned (except the newest due period), so late publication can also leave gaps. No gap-free continuity is guaranteed.

**Source revisions:** each run revalidates at most 4 stored periods (and at most one quarter of its request budget): rows with a non-ACT code, and rows labelled within the last 2 hours (one recheck about an hour after collection), non-ACT and newest first. Each period is rechecked at most hourly. Simulated steady state: about 850 GSE requests/day, within the production worker's 500-1000/day envelope (docs/sources/gse.md). Corrected bytes update the record and revision counter; identical bytes do not. Corrections outside the window or beyond the bounded budget may remain undiscovered.

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
- The MW forecast needs at least one week of paired data. The historical forecast archive format (Open-Meteo historical forecast API) could not be verified live from the development environment, which hit Open-Meteo's daily per-IP limit; if the format differed, the collector records the refusal and the model falls back to the project's own archive.
- Accuracy scores start empty and grow with the archive; ERA5-based scores lag by about 5 days.
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
