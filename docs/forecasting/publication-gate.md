# MW forecast publication gate

The website MW forecast section (`forecast_display.py`, `forecast_page._mw_forecast`) is
implemented and tested, but stays **off** while `mwmodel.PUBLISH_FORECAST = False`. The numeric
forecasts are already public in the `forecast-data` branch (ledger and `evaluation/latest.csv`).
The switch controls only whether the website shows them.

## Evidence that counts

| Source | What it is | Counts for the gate |
|---|---|---|
| `live` leaderboard | Forecasts as issued in real time (since 20.11.2026), scored afterwards | **yes** |
| `backtest` leaderboard | Rolling-origin replay of past data, with models fixed in hindsight | no (supporting only) |

## Criteria (`streamlit_cloud/forecasting/gate.py`)

A model passes the gate at a given cadence and horizon only if **all** of these hold, on `live` data:

1. At least **28 independent local days** and **500 complete cases**. Fourteen days is too short for
   wind: one or two weather regimes can dominate it. Four weeks cover several regimes and four
   weekly cycles.
2. Skill against persistence greater than 0, with the **90 % day-block bootstrap interval
   entirely above 0**.
3. **|bias| ≤ 0.3 × MAE**, so that systematic offset does not dominate the error.
4. An operationally complete record: **late share ≤ 10 %** and **≥ 90 %** of matured forecasts
   scoreable.

Persistence is the reference model and is never published as a forecast.

**Enforcement (fail closed).** Even when `PUBLISH_FORECAST` is on, the page shows **only** the
(model, cadence, horizon) keys that pass the gate. These keys are evaluated on the live leaderboard
before the chart and table are built.
- If no key passes, no MW value is shown and the page explains why.
- Rows of other horizons or models are withheld. They are not merely labelled.
- Persistence is never offered.
- Freshness is checked on the selected series: a data cutoff older than 60 min is stale.
- An issue time or cutoff in the future (beyond 5 min clock skew) is rejected.
- Plausibility bounds: −1 MW to 105 % of the nameplate figures in `capacity.py`. Rows outside are
  dropped, never clamped.

Showing unvalidated numbers would be a different, explicit owner decision.

## Current evidence (leaderboard 22.11.2026 07:16 UTC)

1-hour cadence. Skill is against persistence; CI is the 90 % day-block bootstrap.

| Horizon | Live: damped trend MAE / skill [CI] | Live days | Backtest: damped trend MAE / skill [CI] | Backtest days |
|---|---|---|---|---|
| 1 h | 12.9 MW / +0.16 [+0.09, +0.31] | 2 | 12.4 MW / +0.20 [+0.11, +0.29] | 16 |
| 2 h | 21.5 MW / +0.04 [-0.02, +0.16] | 2 | 20.5 MW / +0.13 [+0.06, +0.20] | 16 |
| 3 h | 26.3 MW / -0.01 [-0.15, +0.21] | 2 | 27.1 MW / +0.10 [+0.04, +0.15] | 16 |
| 6 h | 35.3 MW / -0.05 [-0.10, -0.01] | 2 | 44.5 MW / +0.06 [+0.03, +0.08] | 15 |
| 12 h | 25.4 MW / -0.55 | 2 | 65.5 MW / -0.01 [-0.04, +0.01] | 15 |
| 24 h | 25.5 MW / -0.55 | 2 | 58.8 MW / -0.05 [-0.11, -0.00] | 14 |

Climatology is far worse than persistence at every horizon.

- **Gate status: no horizon passes**, because there are only 2 live days.
- **Earliest possible pass: about 18 December 2026**, which is 28 live days after 20.11. That
  assumes continuous collection and only if the skill holds.
- **Expected outcome:** the backtest suggests damped trend helps only at **1-6 h**. At 12-48 h
  no stage-I model beats persistence. Longer horizons need the weather-driven tournament models
  (#67, #65/#66) to prove themselves under the same gate.

## Limitations

- **Small sample.** Two live days and about 16 backtest days. The backtest covers a single
  late-autumn period, with no seasonal coverage.
- **No uncertainty band.** The stage-I baselines produce no q10/q90, so none is drawn. A band is
  shown only when the file carries genuine quantiles.
- **Units and scale.** MW is the national wind total from GSE 3-minute data. The capacity basis
  is not normalised, because new farms change the fleet.
