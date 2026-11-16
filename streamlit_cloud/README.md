# Streamlit Community Cloud pilot

Owner selected Community Cloud and authorized public deployment and GSE/Open-Meteo retrieval in Issue #18. The original Next.js/FastAPI/PostgreSQL deployment is preserved. This is an on-demand pilot, **not feature-equivalent continuous monitoring**.

## Deploy

- Repository: `GiorgiKhorbaladze/Georgia-WindCast`
- Branch: `work/streamlit-cloud` (deploy the separately reviewed branch; no automatic main merge)
- Entrypoint: `streamlit_cloud/app.py`
- Python: 3.12
- Requested subdomain: `georgia-windcast` (subject to availability)
- Requirements: `streamlit_cloud/requirements.txt`
- No app secrets or paid services required. Streamlit manages HTTPS.

## Data and lifecycle

A process-wide locked source cache is shared by sessions. Open pages refresh every 180 seconds; idle/sleeping apps do not collect. GSE is fetched at most every 180 seconds, three recent candidate files maximum, successful candidates not re-requested; unpublished/failed candidates retried at most three times with at least 180 seconds between attempts. 404 means not available; failures are cached with exponential backoff and Retry-After. A bounded three-period lookback can still leave collection gaps. Generation retains up to seven days **in memory only**, with original label, quality, retrieval time, URL and SHA256. Restart/redeploy/sleep can erase it. Do not call this a permanent archive.

Forecast metadata is checked every 15 minutes; the data is fetched only on a changed ICON run, metadata verified before/after, and earlier valid hours excluded. Cached data keeps its retrieval timestamp after failure. Forward coverage requires consecutive non-null hourly speed and direction, capped at 72 hours. ERA5 is fetched on the History page, at most daily, for seven days ending five days ago. No values are imputed. UI times are Asia/Tbilisi; stored datetimes and generation CSV are UTC. GSE non-ACT records are withheld from the headline but retained as explicitly labelled raw source history.

Required for full production equivalence: external persistent storage, independent permitted collector, outage monitoring and off-host backup. No background keepalive is installed. No fixture data is imported by the production entrypoint.

## Verify locally

```
python -m pip install -r streamlit_cloud/requirements.txt pytest==8.4.2
python -m pytest streamlit_cloud/tests -q
streamlit run streamlit_cloud/app.py
```

Tests use recorded source fixtures plus labelled mutations through HTTP mock transport; do not contact upstream. Streamlit AppTest exercises all pages in Georgian and English. Actual cloud source reachability, browser layout and HTTPS must be separately checked after deployment. Phone emulation is not a real iPhone/Safari check.
