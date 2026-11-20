# Wind generation forecasting - stage I (Issue #57)

Experimental. Nothing here is shown as a public forecast; `mwmodel.PUBLISH_FORECAST` stays `False`.

## What runs
`.github/workflows/forecast.yml` runs after every successful GSE collection (every 15 min). It
reads only the `data` branch (no request to GSE or any weather provider) and writes the
`forecast-data` branch:

| Path | Content |
|---|---|
| `ledger/YYYY/MM/YYYY-MM-DD.csv.gz` | Append-only live forecasts (contract `wind_forecast_ledger/v1`) |
| `backtest/ledger/...` | Rolling-origin replay: simulated issue time = cutoff, models see only data <= cutoff |
| `evaluation/leaderboard.json` | Scores per cadence x horizon x model (live and backtest, separately) |
| `evaluation/history_*.csv` | Daily accuracy history per model, cadence and horizon |
| `evaluation/day_ahead_*.csv` | Day-ahead MWh from hourly forecasts covering a full local day |
| `evaluation/latest.csv` | Latest issue, with data cutoff and issue time |
| `constraints.csv` (optional) | Confirmed operational constraints, public `https` source required |

## Contract
Each record: `model_id`, `model_version`, `feature_version`, `cadence` (3m/15m/1h),
`issued_at_utc`, `data_cutoff_utc` (last GSE label used), `weather_run_utc`, `valid_from/to_utc`,
`prediction_mw`, `q10/q90`, `capacity_basis`, `inputs_sha256`, row hash. Validation refuses a
cutoff or weather run after the issue time and any interval that starts before the cutoff.

Two leads: **horizon** = valid_to - data cutoff, **effective lead** = valid_to - issue time. With a
15-minute collector, a 3-minute nowcast issued at the next collection is often already *late*
(valid_to <= issued_at). It is archived and scored but never presented as a forecast of the future.

Horizons: 3m: 3, 6, 9, 12, 15 min · 15m: 15 min to 6 h · 1h: 1 to 48 h. Daily MWh is
the sum of 24 hourly forecasts from one issue made before the local day starts.

## Models
Stage I baselines: `persistence` (skill reference), `damped_trend`, `climatology` (local hour of
day, 28 days). Candidates listed but not enabled or ranked: Ridge+ICON (existing `mwmodel.py`),
SARIMA, SARIMAX, XGBoost, LightGBM, CatBoost, GRU (`forecasting/models.py: CANDIDATES`).

## Scoring
Only complete intervals (every GSE period stored); models compared on common cases only (same
cadence, horizon, cutoff, interval); MAE, RMSE, Bias in MW; skill = 1 - MAE/MAE(persistence) with
a day-clustered bootstrap 90 % interval. A bucket with < 14 independent days or < 200 cases is
`insufficient_evidence`; no "best model" is declared from it, and 14 days is a floor, not proof.
Periods are never removed for suspected curtailment; confirmed constraints (public source) are
reported as a second score next to the full one.

## Capacity and capacity factor
`forecasting/capacity.py`: Kartli 20.7 MW and Zemo 18.75 MW are owner-supplied starting values
(unverified); Ruisi capacity and staged commissioning are not established from an official source.
Capacity-factor models stay off while any operating capacity is unverified; MW models run.

## Weather predictors (collection owner-approved 20.11.2026)
`forecasting/weather_points.py` stores ICON (`icon_global`) forecasts of temperature, humidity,
precipitation, rain, sea-level and surface pressure, cloud cover and wind (10/80/120 m, gusts) at
seven points: Batumi, Poti, Kutaisi (west), Surami pass (central), Kartli/Ruisi cell, Zemo and
Tbilisi (east).

- One batched request per NEW run, detected from the collector's `weather/forecast_meta.json`
  (no extra polling); the run is checked against Open-Meteo metadata before and after the request.
- About 4 data requests and 8 metadata checks a day; estimated weighted calls < 100/day (free tier
  10,000/day). After a 429 or other failure, no request for one hour.
- Stored as the exact response (gzip) with SHA-256, run time, retrieval time and the grid cell of
  every point; points resolving to the same cell are listed (not independent predictors).
- As-of rule: a model issued at T uses a run only if run <= T and retrieved <= T.
- Hypothesis (west precipitation vs. east wind) and ablations (local wind / local weather /
  local + west) are evaluated in the challenger stage; nothing is assumed in advance.

## Monthly
`forecasting/monthly.py`: per-station same-month Q10/Q50/Q90 from >= 5 comparable years (the
partial commissioning year excluded); fleet total only when every operating station qualifies.
