# Weather model data - Open-Meteo integration

Issue: #4. Verified 2026-11-14. Every value is **model-derived wind (m/s)**. None is an anemometer measurement, and none is a generation (MW) forecast.

## Products

| Product | Provider / model | Heights | Use in WindCast | Provenance stored |
| --- | --- | --- | --- | --- |
| Forecast | Open-Meteo `/v1/forecast`, `models=icon_global` (DWD ICON, about 13 km) | 10, 80, 120, 180 m | 72 h forecast; past hours from the shortest-lead earlier run | model, **run initialisation time** (from `/data/dwd_icon/static/meta.json`), valid time, retrieval time, model grid point |
| Reanalysis | Open-Meteo `/v1/archive`, `models=era5` (ECMWF ERA5, 0.25°) | 10, 100 m | Historical model context (latency about 5 days; recent hours are `null` and not stored) | model, valid time, retrieval time, grid point |

- **200 m is not offered by any Open-Meteo product** and is reported as unsupported.
- **100 m** exists only in the reanalysis. The forecast API documents 80 and 120 m but not 100 m. Nothing is interpolated between heights.
- Direction follows the meteorological convention (degrees the wind blows **from**). The map and charts draw arrows pointing **downwind** (bearing + 180°); a unit test checks this.

### Why `icon_global` and not `best_match` or `icon_seamless`

`best_match` and `icon_seamless` blend models or domains with different run times. A single run time could not then be attributed honestly. `icon_global` covers 72 h from every run, and its run time is published in `meta.json`. The worker reads the run time **before and after** fetching the forecast and discards the data if they differ. It stores only valid times at or after the run's initialisation, because Open-Meteo fills earlier hours from older runs.

## Request budget and politeness

- All three sites go in **one request** (comma-separated coordinates; the response is a list in request order).
- `meta.json` is checked every `WINDCAST_WEATHER_POLL_SECONDS` (900 s). The forecast itself is fetched only when a **new run** appears (4 runs a day). Reanalysis is fetched once every 24 h for a 10-day trailing window, then upserted because ERA5 values are revised.
- Steady state is about 100 small metadata requests and about 5 data requests per day.
- 429/5xx, timeouts, provider error bodies and schema changes trigger persisted exponential backoff. `Retry-After` is honoured and capped at 1 h.

## Evidence (2026-11-14)

- `meta.json` for `dwd_icon_eu` returned `last_run_initialisation_time` = 2026-11-14T15:00Z (available 17:55Z); `dwd_icon` returned 12:00Z.
- The archive with `models=era5`, 3 sites, returned grid points (42.0, 44.0), (42.0, 44.25) and (42.0, 44.0) for Ruisi, Zemo and Kartli respectively. Values for the most recent 2-3 days were `null` (ERA5 latency).
- **Live check after the quota reset (2026-11-15 00:10 UTC, `docs/evidence/weather/live-check-20261115T0010Z.json`):** run metadata reported ICON run 2026-11-14T18:00Z. The forecast returned 96 h × 4 heights for all 3 sites with no nulls. Grid points: Ruisi (42.0, 44.0), Zemo (41.875, 44.375), Kartli (42.0, 44.0), so Ruisi and Kartli are identical. The reanalysis responded; the most recent days were `null` (ERA5 latency). Recorded fixtures: `backend/tests/fixtures/openmeteo/real_*`.
- **Quota incident:** the forecast API answered `429 {"reason":"Daily API request limit exceeded"}` with `X-RateLimit-Limit: 10000`, `X-RateLimit-Window: 86400` and `Retry-After` about 3.2 h. Later the archive did too. The limit is **per IP**, and the development sandbox shares its egress IP with other users. A deployment with its own IP needs about 100 requests per day. The live forecast check was repeated after the quota reset (see the PR for the result).

## Licence and terms (owner decision)

Open-Meteo's free API is for **non-commercial** use, and data is CC BY 4.0 with attribution "Weather data by Open-Meteo.com". The UI shows this attribution, plus the DWD ICON and ERA5 (Copernicus) credits. If WindCast is used commercially or within a commercial organisation's operations, an Open-Meteo API subscription (or self-hosting) is required. **The owner must confirm the use category** before enabling `WINDCAST_WEATHER_INGESTION_ENABLED=true` in a deployment.

## Live verification

```bash
cd backend && uv run python -m app.ingestion.live_check_weather   # read-only, 3 requests
```
