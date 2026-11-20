# Monthly wind generation history (Issue #52)

Monthly **energy** (GWh) per wind farm, from October 2016. It is separate from the 3-minute
instantaneous **power** (MW) archive written by `collect-gse.yml`: different source, workflow,
state file and failure status.

## Sources

| Source | Role | Status in archive |
|---|---|---|
| Owner workbook `qaris_sadgurebis_gamomushaveba_2016_2026.xlsx` (sha256 `dd346670…4f311`, 3 sheets) | Initial seed: 118 Kartli months (2016-10…2026-07) and 5 Zemo months (2026-03…07) | `owner_compiled_unverified` until matched |
| GSE "ფაქტიური ბალანსი" page, yearly PDFs 1995-2026 | Primary source; links discovered from the page's own content API `https://admin.gse.com.ge/api/ka/menu/faqtiuri-balansi-125` | `gse_document_verified` / `gse_document_pending_approval` |

`candidate.gse.com.ge` (the link in the issue) was blocked by this environment's proxy. The
same page is served by GSE's main site, whose content API lists every document with an id, the
year and an `https://admin.gse.com.ge/...pdf` link. No document URL is hard-coded: each check
reads the page again, and links to any other host are ignored.

Document format, verified on the 2016-2026 files: one page per year, exported from a spreadsheet,
title `საქართველოს ელექტროენერგიის ბალანსი YYYY წლის`, unit million kWh (= GWh), months
January-December plus `სულ` (total). 2016-2019 use dot decimals (`1,061.152`), 2020+ comma
decimals with space thousands (`1 102,67`). Kartli's row label changed from
`ქართლის ქარის ელ.სადგური` (2016-2025) to `ქართლის ქარის ელექტროსადგური` (2026). The 2026 file
adds Zemo, Ruisi and a `სულ ქარის სადგურები` total row.

GSE has not published reuse terms (see `docs/sources/rights.md`, Issue #18). **Automated retrieval
and redistribution stay disabled until the owner confirms rights** (see "Activation").

## Storage (`data` branch, `history/`)

| File | Content |
|---|---|
| `wind_monthly.csv` | Current view, unique key `(station_id, year, month)` |
| `wind_monthly_revisions.csv` | Append-only ledger; ids strictly increasing; never rewritten |
| `sources.json` | Per-year document registry: file id, URL, sha256, ETag, Last-Modified, bytes, state, error, previous hashes |
| `monitor_state.json` | `last_attempt_at`, `last_success_at`, `last_page_sha256`, `last_result` |

Before the first monitor run the archive is bootstrapped from `streamlit_cloud/history_seed/`
(the reviewed importer output). An incomplete archive is never re-seeded.

`wind_monthly.csv` columns: `station_id, name_ka, name_en, year, month, energy, unit (GWh),
verification_status, source_kind, source_url, source_document_id, source_sha256, retrieved_at,
published_at (HTTP Last-Modified of the document), revision_id, last_modified, pending_energy,
pending_revision_id, note`.

Energy is stored in GWh exactly as published (no ×1000 conversion that could hide a unit slip).
Values above 400 GWh per farm-month are refused as unit errors.

## Verification states

| State | Meaning | Public |
|---|---|---|
| `owner_compiled_unverified` | Owner workbook value with no matching official document yet | yes, labelled unverified |
| `gse_document_verified` | Owner value equals the GSE document within half a unit of the coarsest printed precision | yes, official |
| `gse_document_pending_approval` | Value only in a GSE document (new month or farm) | **no**, until approved |
| `gse_document_approved` | Pending official value approved by the owner | yes, official |
| `conflict_unresolved` | Owner value differs from the GSE document; displayed value unchanged, GSE value in `pending_energy` | yes, flagged |

A GSE revision of a month already shown is stored in `pending_energy` / `pending_revision_id` and
replaces the displayed value only after approval. Changes above 10 % are listed in the run
report's `flags`.

## Zero, missing and partial

- A blank PDF cell means *not reported*: no row is created. A printed `0` is a reported zero.
- The workbook's sheet 3 has zeros for Zemo from 2016-10 to 2026-02 while the Zemo sheet is
  blank: 113 placeholders, **not imported**.
- Kartli October 2016 = 0 in both the workbook and the GSE 2016 balance: imported as a reported
  zero (commissioning month).
- Annual totals are recomputed from months; a year is complete only with all 12 months.
- Nothing is interpolated, extrapolated or taken from national aggregates.

## Reconciliation, 20 Nov 2026 (offline run on the genuine PDFs)

| Year | GSE file id | File | Bytes | sha256 |
|---|---|---|---|---|
| 2016 | 236 | `01KN70A79HE01TC0XAYV9G9M1F.pdf` | 104,452 | `e831e589ce38e43b…` |
| 2017 | 237 | `01KN70B1YAQ75SGK8E7X6KS5W8.pdf` | 112,267 | `36980df6902b14c7…` |
| 2018 | 238 | `01KN70C028DZBT9WAH2V2TSH69.pdf` | 112,132 | `e58ec0017eced1b9…` |
| 2019 | 239 | `01KN70CQQNNXZBKK6KG7D9MSQZ.pdf` | 116,561 | `cfa9c3a9cc1f9ad5…` |
| 2020 | 240 | `01KN70DG3HR7RBZNPW844PB6ZA.pdf` | 114,809 | `becbc684b3b7ae1a…` |
| 2021 | 241 | `01KN70E3AWJBVK3Y9EFXMWE7JK.pdf` | 115,393 | `758768a508166672…` |
| 2022 | 242 | `01KN70ETCV5WKSGW17W9HSFTWE.pdf` | 115,702 | `7d14268e00d2cd47…` |
| 2023 | 243 | `01KN70FTQGJPAE6DF8Z9P3958S.pdf` | 112,636 | `a781bd3f117e97c3…` |
| 2024 | 244 | `01KN70GCQQYMVXZPHQY40P941H.pdf` | 114,169 | `9df91440ffa90cca…` |
| 2025 | 245 | `01KN70H1N74XSYEQ9FHXE7B59F.pdf` | 191,342 | `133cfbaf052ea588…` |
| 2026 | 365 | `2026_Oct_Geo.pdf` (data through October) | 227,839 | `6c42f49504327aa1…` |

Result: all 11 documents parsed and passed the row-total and wind-total checks.

- **123 of 123** workbook records match the GSE documents → `gse_document_verified`. No conflicts.
- **8 records exist only in the GSE 2026 document** → `gse_document_pending_approval`:
  Kartli Aug-Oct (6.52, 6.00, 6.34), Zemo Aug-Oct (3.44, 3.76, 4.14), Ruisi Sep-Oct (0.31,
  33.27) GWh.
- The 2016 document prints more decimals (Nov 1.83474, Dec 7.19098) than the workbook (1.83, 7.19).
  The workbook values stay displayed: they match within the printed precision.
- Printed annual totals are rounded (e.g. 2016 `9.0`, 2017 `87.8`); the archive's totals are
  recomputed from months (2016: 9.02, 2017: 87.74).

Ruisi October 2026 (33.27 GWh) is far larger than its September value (0.31). It is consistent
with the document's own wind total (43.75 = 6.34 + 4.14 + 33.27) but should be reviewed by the
owner before approval (likely the first full month after commissioning; not verified here).

## Monitor (`.github/workflows/history-monitor.yml`)

- Wakes daily at 03:41 UTC; contacts GSE only when ≥ 72 h have passed since the previous
  **attempt** (successful or not). Earlier wake-ups report `skipped_not_due` with no request.
- One page request, then one conditional request per yearly document from 2016
  (`If-None-Match` / `If-Modified-Since`). Unchanged hashes are not re-parsed.
- Document states: `unchanged`, `new`, `updated`, `missing` (removed from the page; data kept),
  `download_failed` (HTTP error, CAPTCHA/HTML instead of PDF, > 5 MB), `unsupported_structure`
  (title/year/header changed or an unregistered wind farm row), `validation_failed` (months do
  not add up to the printed total, stations do not add up to the wind total, implausible value).
  A refused document changes nothing in the archive.
- Exit 1 for a refused document or failed download, 2 when the page cannot be read.
- Shares the `collect-gse` concurrency group only so that the two workflows never push to the
  `data` branch at the same moment.

New wind farms: add the exact GSE row label to `STATIONS` in `streamlit_cloud/wind_history.py`
(reviewed PR). Until then the document is quarantined as `unsupported_structure`.

## Activation (owner actions)

1. Confirm GSE reuse rights (Issue #18).
2. Merge PR A, then run the workflow manually (`mode: force_check`) once and review the report.
3. Approve pending values: `mode: approve`, `approve_through: <revision id>`, `reason: …`.
4. Set repository variable `HISTORY_MONITOR_ENABLED=true` to enable the scheduled three-day check.

Until step 4 the scheduled run is skipped by GitHub (`if:` on the job), costing nothing.

## Re-running the import

```
python streamlit_cloud/wind_history_import.py qaris_sadgurebis_gamomushaveba_2016_2026.xlsx \
  --out streamlit_cloud/history_seed --imported-at 2026-11-20T00:00:00+00:00
```

The output is byte-identical for the same workbook and timestamp. The workbook itself is not
committed; its sha256 and size are in `history_seed/import_report.json`.
