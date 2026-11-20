# Forecasting stage II - challenger tournament (Issue #57)

Experimental; `PUBLISH_FORECAST` stays `False`. `.github/workflows/forecast-tournament.yml` runs once a
day (02:17 UTC) and writes `forecast-data/evaluation/tournament.json` plus the per-case predictions.

## Protocol
- Target: hourly mean GSE MW, only hours with all 20 three-minute periods. Horizons 1, 3, 6, 24 h.
- Issue time t = hour boundary; features known at t: GSE lags (1-24 h), 6-h mean, last change,
  target hour of day; weather from the newest run with run <= t and retrieved <= t.
- Rolling origin by local day: for test day D each model trains only on rows whose target hour ended
  before D begins (no overlap), then predicts every issue of D. First 5 days are training only.
- Scores on cases that every available model predicted; MAE, RMSE, Bias; skill vs persistence with a
  day-block bootstrap 90 % interval. **The unit of independence is the day**: the 57,456 stage I
  backtest forecasts are 13 days of data, not 57,456 independent tests. Below 14 independent days
  every row is `insufficient_evidence` and nothing is ranked; 14 days is a floor, not proof.
- Variants: `gse_only`; once as-of weather runs exist, `local_weather` (east) and
  `local_plus_west` (east + central + west, with west-east pressure difference and west
  precipitation) - the owner's west-rain / east-wind hypothesis is tested as an ablation.

## Models (fixed hyper-parameters, `forecasting/mlmodels.py`)
persistence (reference), ridge (numpy), SARIMA(1,0,1)x(1,0,0,24) (statsmodels; becomes SARIMAX when
as-of weather covers the training period), XGBoost, LightGBM, CatBoost (native APIs, 300 rounds,
seed 57), GRU (torch CPU, hidden 16, 48-h window, 40 epochs). A missing library is reported as
`unavailable`; a failing model is reported as `error` and the others continue.

## First real run (local, 8-20 Nov 2026; 5 training days, 6-7 test days)
All rows `insufficient_evidence`. Persistence was best at 1 h and 3 h; SARIMA was marginally ahead
at 6 h and 24 h with intervals spanning zero; ridge and the tree models were worse than
persistence (expected with 5-12 days of training and a fleet that changed in October).
