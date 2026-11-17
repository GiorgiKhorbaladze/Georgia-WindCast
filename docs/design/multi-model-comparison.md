# Multi-model wind comparison: feasibility and licensing note (Issue #33, feature 4)

Status: **design note for owner approval. No code, no new provider request, no ingestion.**
Prepared 17.11.2026.

## Sources used and what could not be checked

- **Primary documentation used:** the source of Open-Meteo's own documentation site, repository `open-meteo/open-meteo-website`, branch `main`, fetched 17.11.2026:
  - `src/routes/en/docs/ecmwf-api/+page.svelte` and `options.ts`;
  - `src/routes/en/docs/gfs-api/+page.svelte` and `options.ts`;
  - `src/routes/en/terms/+page.svelte`.
- **Could not be reached from this session** (DNS blocked): `open-meteo.com`, `ecmwf.int` and `nco.ncep.noaa.gov`. The rendered pages should be re-checked from an unrestricted machine before approval.
- **Already verified in the project:** the ICON integration (`docs/sources/weather.md`).

## Candidate models (all through the same provider, Open-Meteo)

| Model | `models=` value | Native grid / time step (per Open-Meteo docs) | Wind heights offered | Notes |
| --- | --- | --- | --- | --- |
| DWD ICON global (current) | `icon_global` | ~13 km, hourly | 10, 80, 120, 180 m | In use; run time from `meta.json` |
| ECMWF IFS HRES | `ecmwf_ifs` | 9 km (O1280), runs every 6 h; 1-hourly to +90 h, then 3-hourly, then 6-hourly after +144 h | 10, 100, 200 m | Open data since 1.10.2025 under CC BY 4.0 (Open-Meteo states this) |
| ECMWF IFS open data | `ecmwf_ifs025` | 0.25°, 3- and 6-hourly, about +2 h extra delay | 10, 100, 200 m | Coarser; not recommended |
| ECMWF AIFS | `ecmwf_aifs025_single` | 0.25°, 6-hourly only | (same variable list) | Machine-learning model; time step too coarse |
| NOAA GFS | `ncep_gfs_global` (`ncep_gfs_seamless` blends) | "0.11°/0.25°" (label in docs) | 10, 80 m | Seamless blends models and is not used, for the same reason `best_match` is not used for ICON |

**Temporal interpolation:** Open-Meteo "dynamically interpolates all data to a consistent 1-hourly time-series". For models with 3- or 6-hourly native steps, hourly values are interpolated by the provider. A comparison must therefore:
- restrict itself to lead times where the model is natively hourly (IFS HRES up to +90 h); or
- flag interpolated hours.

## Common heights: no extrapolation

| Height | ICON | ECMWF IFS | GFS |
| --- | --- | --- | --- |
| 10 m | yes | yes | yes |
| 80 m | yes | no | yes |
| 100 m | no | yes | no |
| 120 / 180 m | yes | no | no |

- **Three-model comparison:** only possible at **10 m**.
- **Hub-relevant heights:** a like-for-like comparison is possible only for **ICON vs GFS at 80 m**.
- **ECMWF:** it can be compared with ICON only at 10 m. ECMWF 100 m vs ICON 80/120 m would need vertical extrapolation, which the assignment excludes unless separately validated and approved.

## Licence, terms and cost

- **Open-Meteo free API:**
  - **non-commercial use only**;
  - under 10,000 calls per day, 5,000 per hour and 600 per minute (terms page source);
  - commercial use (subscriptions, advertising, commercial products or promotion, undisclosed research at commercial entities) requires a paid API subscription.
- **Open-Meteo data:** CC BY 4.0 with attribution.
- **ECMWF IFS:** open data under CC BY 4.0, as stated by Open-Meteo. ECMWF's own licence page could not be reached here and must be checked.
- **NOAA GFS:** not verified here. US government model data is commonly public domain, but this needs checking on NOAA's pages.
- **Project position:** the project's use category (non-commercial showcase vs. business lead generation) is still the open owner decision recorded in #18. **No multi-model ingestion should start before that decision.**
- **Cost:** none on the free tier, if the use is non-commercial.

## Request budget (if approved)

- **Pattern:** the same as ICON. All three sites go in one request per model; data is fetched only when a new run appears. That is 4 runs a day per model, plus about 96 small run-metadata checks a day per model.
- **Estimate:** about 2 models × (4 data + 96 metadata) ≈ 200 extra requests per day, far below 10,000 per day.
- **Shared-IP caveat:** the collector runs on GitHub-hosted runners with shared IPs, which hit the per-IP limit once in development (`docs/sources/weather.md`).
- **Run-time metadata endpoints for ECMWF and GFS:** not verified. One read-only request per model would be needed after approval.

## How a comparison would be shown (if approved)

- **Alignment:** same site, same height, same valid hour, m/s. Each model at its own nearest grid point; grid points are shown, because Ruisi and Kartli share an ICON point.
- **Model-to-model spread** (for example min-max or absolute difference), **not** accuracy. No model is called "more accurate" because models agree.
- **Accuracy:** a skill ranking needs a measured reference (none is available) or a clearly labelled model reference, as on the current accuracy page.
- **Missing values:** missing hours stay visible, and interpolated (non-native) hours are flagged.

## Decisions requested from the owner

1. The use category: non-commercial, or a paid Open-Meteo plan (also needed for ICON; see #18).
2. Approval of the candidates. **Recommended:** `ecmwf_ifs` at 10 m and `ncep_gfs_global` at 10/80 m. **Not recommended:** AIFS and IFS 0.25° (coarse time steps), and the seamless or blended variants.
3. Approval of the scope: 10 m three-model spread plus 80 m ICON vs GFS, with no vertical extrapolation.
4. Permission for one read-only verification request per model (schema, grid points, run metadata) before any ingestion.
