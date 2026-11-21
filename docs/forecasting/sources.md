# Weather sources for forecasting (Issue #57, owner decision 21.11.2026)

| Source | Model | Access | Steps | Status |
|---|---|---|---|---|
| Open-Meteo | DWD ICON global (`icon_global`) | JSON API, free non-commercial tier | hourly, 96 h | active (#62) |
| NOAA GFS | GFS 0.25 deg | AWS Open Data `noaa-gfs-bdp-pds`, no key | 3-hourly, 0-72 h | this PR |
| ECMWF | IFS 0.25 deg open data (CC BY 4.0) | AWS Open Data `ecmwf-forecasts`, no key | 3-hourly, 0-72 h | this PR |
| DWD | ICON-EU direct (`opendata.dwd.de`) | GRIB2, no key | hourly | next: backup channel; same model family as Open-Meteo ICON, **not an independent model** |
| Visual Crossing | blend | API key (free tier 1,000 records/day) | hourly | next: pilot, needs the owner's free key |
| AccuWeather | - | 14-day trial, no historical forecasts | - | not planned (no as-of history for validation) |

## How a run is stored
`forecast-data/weather/sources/<gfs|ecmwf>/`: `manifest.json` (run time, S3 LastModified =
published, retrieval time, grid cell of each point, SHA-256 of every GRIB message used and of the
stored table) and `runs/<run>.csv.gz` (point, valid time, variable, value, canonical units).

- Only the needed GRIB2 messages are downloaded (byte ranges from the official `.idx` / `.index`),
  decoded with ecCodes and read at the nearest grid point. Roughly 230 MB (GFS) and 140 MB (ECMWF)
  per new run; about 4 runs a day each. No data is interpolated in time.
- Canonical variables: temperature 2 m, relative humidity 2 m (IFS: from dew point), MSL and surface
  pressure, precipitation per 3-h step (de-accumulated), cloud cover, wind speed/direction at 10 m
  and 100 m, gusts (IFS step 0 has none).
- A run is taken only when its last needed step is published; each run is stored once.
- As-of: a model issued at T may use a run only if run <= T and retrieved <= T.

## First live check (21.11.2026, 3 steps each)
GFS 00 UTC (published 03:36) and IFS 18 UTC (published 00:27) were stored; 224 values each; GFS
27.6 MB / 42 requests, IFS 17.1 MB / 39 requests. Grid cells: Kartli/Ruisi (42.0, 44.0), Zemo
(42.0, 44.25), Kutaisi (42.25, 42.75) etc. - all seven points fall in different 0.25 deg cells.
