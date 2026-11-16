# Streamlit demo edition

`streamlit_app/` is a reduced, **database-free** edition of Georgia WindCast for Streamlit Community Cloud (free). It is a demo, not the full product.

| | Streamlit demo | Full product (Docker, [DEPLOY-ORACLE.md](DEPLOY-ORACLE.md)) |
| --- | --- | --- |
| GSE national wind aggregate | Latest value + last **3 hours**, kept in memory; restarts empty after an app restart or sleep | Continuous ingestion, PostgreSQL history (24 h / 7 d / 30 d / custom) |
| Site wind forecast | Current DWD ICON run via Open-Meteo, 4 heights, last good forecast kept on errors | Same, plus ERA5 reanalysis and stored provenance |
| Map | Simple site map | MapLibre map with wind arrows |
| Edge security (Caddy, rate limits, segmentation) | Provided by Streamlit's hosting, not by this repository | Yes (PR #20) |

The demo reuses the production rules from `backend/app` unchanged: the strict defusedxml GSE parser, the period/label validation (`app/ingestion/gse_periods.py`), the strict Open-Meteo parser, the verified site list, and the same freshness rules (age from the source label, quality ≠ `ACT` shown as unverified, forecast run age and forward coverage). Missing periods are shown as gaps; nothing is invented or interpolated.

## Deploy (owner, about 5 minutes)

1. Sign in at <https://share.streamlit.io> with GitHub and allow access to private repositories. Streamlit asks for an extra GitHub scope for private repositories.
2. **Create app** → *Deploy a public app from GitHub*:
   - Repository: `GiorgiKhorbaladze/Georgia-WindCast`
   - Branch: `main` (after the PR is merged)
   - Main file path: `streamlit_app/streamlit_app.py`
   - App URL: for example `georgia-windcast.streamlit.app`
   - **Advanced settings → Python 3.12**
3. Optional, under *Secrets*: `WINDCAST_GSE_USER_AGENT = "..."` and `WINDCAST_WEATHER_USER_AGENT = "..."` (an identifying User-Agent; not secret, no keys are needed).
4. **Visibility:** an app from a private repository is private by default, and an account can have only one private app. Check *Share* → visibility, and make it public only when you intend to publish it.

`streamlit_app/requirements.txt` (pinned) and `.streamlit/config.toml` (usage stats off, error details hidden from visitors) are picked up automatically.

## Upstream load (polite by design)

| Source | Requests |
| --- | --- |
| GSE | 60 files once at start (4 in parallel); then about 1 new file per 3 minutes, at most one refresh per 30 s for all visitors together; published files are fetched once; missing old periods are abandoned after 3 tries; failures back off exponentially |
| Open-Meteo | At most 3 requests (run metadata, forecast, run metadata) per 15 minutes for all visitors; failures back off from 5 minutes up to 2 hours |

## Known limits and risks

- **No history.** Streamlit Community Cloud gives no persistent storage, and apps sleep after 12 hours without visitors. The demo therefore never claims history beyond its 3-hour window.
- **Shared IP addresses.** Open-Meteo's free tier is limited per IP, and cloud hosts share IPs. A `429` was observed from a shared IP during testing. The app then keeps the last good forecast with its run time and status, or shows "unavailable".
- **GSE reachability from the hosting region** was tested from this project's environment, not from Streamlit's servers. Verify after the first deployment.
- Data use rests on the **owner-reported authorization** recorded in #18.
- Privacy: the hosting provider's policy applies; the app adds no analytics.

## Local run and tests

```bash
python3 -m venv .demo-venv && .demo-venv/bin/pip install -r streamlit_app/requirements.txt pytest
.demo-venv/bin/streamlit run streamlit_app/streamlit_app.py
cd streamlit_app && ../.demo-venv/bin/python -m pytest -q tests   # offline, recorded payloads
```
