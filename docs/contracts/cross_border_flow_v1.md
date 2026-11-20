# Cross-border flow data contract v1 (`cross_border_flow/v1`)

Status: **draft for review, publication not authorized.** Producer: `streamlit_cloud/interchange.py`
(data/backend lane, Claude Code). Consumer: the system map (frontend lane, Issue #49).
Nothing in this contract is collected, archived or shown publicly until the source rights are
verified and the owner gives an explicit go-ahead (Issue #18, owner split of 20.11.2026).

## 1. What the source actually publishes

Verified on 84 authentic GSE 3-minute files (12.11.2026 19:27 to 20.11.2026 16:27 UTC; one file
every 3 h plus one contiguous hour) and on the two repository fixtures. The XML files were used for
analysis only and are not stored in the repository.

| Block (as published) | `IntchSum` (subtotal) | `Intercha` (individual lines) | Observed in the sample |
|---|---|---|---|
| `TOTAL AZERBAIJAN TIE LINES` | `Azerbaij` | none | 84 distinct values, -40.97 to +36.07 MW, code ACT |
| `TOTAL ARMENIA TIE LINES` | `Armenia` | none | always 0.000000, code SUB |
| `TOTAL RUSSIA TIE LINES` | `Russia` | `Salkhino`, `Java`, `Nakaduli` | subtotal always 0 while lines carry up to 57 MW |
| `TOTAL TURKEY TIE LINES` | `Turkey` | none | 0 to 425.41 MW (0 in 65 of 84), code ACT |

Line records (RUSSIA block only):
- `Salkhino`: always `-0.000000` (zero flow), code ACT (NRE in 4 files).
- `Java`: **18.299999 with code BLS in all 84 files**: a persistent value. It is included in GSE's own
  arithmetic and in the archive's gross import (see §5), but it must not be presented as a live,
  varying measurement.
- `Nakaduli`: 35 distinct values, 0 to 38.82 MW; the only line with a varying reading.

Consequences:
- **Line-level data exists for three records only, all in one block.** For Azerbaijan, Armenia and
  Turkey the source publishes a subtotal, not lines. The consumer must not split, distribute or
  route a subtotal over lines that the source does not publish.
- **A subtotal is not assumed to equal its lines.** In the RUSSIA block it reads 0 while the lines
  sum to tens of MW; `subtotal_minus_lines_mw` reports the difference.
- Every row is `EL='P'`, `IN='MvAvr03m'`: 3-minute average active power in MW. Any other quantity, an
  unknown row kind, a missing subtotal, a duplicate record, an empty identifier, a non-finite or
  implausible value (|MW| > 10 000) makes the whole file invalid: no partial record is produced.

## 1a. GSE's published line list (country mapping evidence)

GSE's own website ("Data from the Power System", retrieved 20.11.2026 via
`https://admin.gse.com.ge/api/en/menu/data-from-the-power-system-224`) lists the main interconnection
lines with country and voltage:

| Country | Line title (as published) | kV | Individual record in the 3-minute XML? |
|---|---|---|---|
| AM | Alaverdi | 220 | no (block subtotal only) |
| AZ | Gardabani - 1 | 330 | no |
| AZ | Gardabani - 2 | 330 | no |
| AZ | Mukhranis Velly | 500 | no |
| RU | Kavkasioni | 500 | **no**, although it is listed |
| RU | Salkhino | 220 | yes |
| RU | Java | 110 | yes (persistent value) |
| RU | Nakaduli | 110 | yes |
| TR | Meskheti (published note: connected through HVDC) | 400 | no |
| TR | Adjara | 220 | no |

- The three XML line identifiers match published line titles exactly, and their published country
  (RU) agrees with the XML block. `published_line` is filled only on such an exact double match.
- **Coverage is incomplete even in the RUSSIA block**: the 500 kV Kavkasioni line has no record.
  `line_coverage` lists, per country, published lines and which of them are individually reported.
- The list gives names, countries and voltages only: no route, endpoint, substation or operator.

## 2. Identifiers and mapping policy

- `source_id` = `<block_country_label>/<kind>/<identifier>`, e.g. `RUSSIA/line/Nakaduli`,
  `AZERBAIJAN/subtotal/Azerbaij`. Stable across files; built only from published strings.
- `published_line` (lines only): `{line_title, country, voltage_kv}` from GSE's published list
  (§1a) when the identifier matches a published title AND the published country matches the block;
  otherwise `null`. Subtotals never get one.
- `block_country_label` is the word GSE writes in the block name. It records **how GSE groups the
  records**, not where a line physically runs, which substations it connects, or who operates it.
- `identifier` is B3 verbatim. No translation, no expansion, no coordinates.
- **No geometry.** The source publishes no route, endpoint or topology. `geometry` is always `null`.
  Drawing a line on a map requires a separate, verified and rights-cleared network dataset and a
  security review (operational grid data); that is outside this contract.

## 3. Time semantics

- `period.label_utc` is the end of the 3-minute interval (GSE convention, same as the wind
  aggregate), stored in UTC. `label_local` is the Tbilisi time string as published.
- One document = one source file = one period. Values from different periods are never mixed.
- A file that GSE has not published (HTTP 404) means "no document for that period". It is
  **not** a zero flow and not a confirmed gap: GSE sometimes publishes late (collector rechecks).

## 4. Document (JSON)

```json
{
  "contract": "cross_border_flow/v1",
  "parser": "gse-interchange-03m/1",
  "period": {"label_utc": "2026-11-14T20:03:00+00:00", "label_local": "15.11.2026 00:03:00",
             "interval_minutes": 3, "label_marks": "interval_end"},
  "provenance": {"source": "GSE 3-minute export", "payload_sha256": "<64 hex>"},
  "sign_convention": "positive_into_georgia",
  "blocks": [
    {"block": "TOTAL AZERBAIJAN TIE LINES", "block_country_label": "AZERBAIJAN",
     "lines_published": false,
     "subtotal": {"source_id": "AZERBAIJAN/subtotal/Azerbaij", "kind": "subtotal",
                  "identifier": "Azerbaij", "mw": -30.897966, "direction": "export",
                  "availability": "reported", "source_quality": "ACT"},
     "lines": [], "flow_mw": -30.897966, "subtotal_minus_lines_mw": null},
    {"block": "TOTAL RUSSIA TIE LINES", "block_country_label": "RUSSIA", "lines_published": true,
     "subtotal": {"source_id": "RUSSIA/subtotal/Russia", "mw": 0.0, "direction": "zero", "...": "..."},
     "lines": [{"source_id": "RUSSIA/line/Java", "kind": "line", "identifier": "Java", "mw": 18.299999,
                "direction": "import", "availability": "persistent_value", "source_quality": "BLS",
                "published_line": {"line_title": "Java", "country": "RU", "voltage_kv": 110}}],
     "flow_mw": 32.746205, "subtotal_minus_lines_mw": -32.746205}
  ],
  "national": {"net_from_ties_mw": 1.848239, "net_from_balance_mw": 14.360352, "residual_mw": 12.512113,
               "gross_import_mw": 32.746205, "gross_export_mw": 30.897966},
  "line_coverage": {"RU": {"published_lines": ["Java", "Kavkasioni", "Nakaduli", "Salkhino"],
                           "individually_reported": ["Java", "Nakaduli", "Salkhino"],
                           "not_individually_reported": ["Kavkasioni"]}, "AZ": {"...": "..."}},
  "line_registry_source": "GSE website, 'Data from the Power System' (interconnection lines table), retrieved 2026-11-20",
  "geometry": null,
  "publication": "not_authorized"
}
```

Field rules:
- `mw`: signed, positive = into Georgia (§5). `-0.000000` is normalised to `0.0`.
- `direction`: `import` (mw > 0), `export` (mw < 0), `zero` (|mw| ≤ 1e-6). Derived from the sign only.
- `availability`:
  - `reported`: value present in the file.
  - `persistent_value`: identical non-zero value in ≥ 20 consecutive periods (one hour) of the series
    the producer saw (`persistence_flags`). Means "do not present as live", not "wrong".
  - Absent document: period not published or not collected; never rendered as 0.
- `source_quality`: raw GSE code (ACT, NRE, SUB, BLS, ...). Meaning unpublished: keep for audit, do
  not translate into "verified", "estimated" or similar, and do not show it in the public UI (owner
  decision of 19.11.2026).
- `flow_mw`: lines when published, else subtotal. This is the rule GSE's own arithmetic follows and
  the rule the archive already uses for gross import/export.

## 5. Sign convention and reconciliation (evidence)

- **Sign:** positive = flow into Georgia. Evidence: in every sampled file whose generation and
  consumption totals carry the code SUB (35 of 84), `consumption - generation` equals the sum of
  `flow_mw` over all blocks to within 0.01 MW. Negative values match exports shown on GSE's site
  (e.g. Azerbaijan on 16.11.2026 22:39, checked earlier).
- **Archive consistency:** gross import/export from this module equal the archived
  `import_mw`/`export_mw` (collector, `balance.py`) in 84 of 84 files.
- **Published arithmetic difference (`residual_mw`):** in all 49 sampled files where generation or
  consumption is coded NRE, `consumption - generation` differs from the tie sum (mean 9.15 MW,
  max 27.54 MW); in all 35 SUB-coded files it is 0. The difference is reported as published. It is
  **not** a measured physical imbalance, loss or unmetered flow; its cause is not documented by
  the source.

## 6. Guidance for the consumer (frontend)

- Show what exists: four block-level flows (country label as published) and, inside the RUSSIA
  block, three line records. Listed-but-unreported lines (e.g. Kavkasioni, all AZ/AM/TR lines) may be
  named from `line_coverage` but must carry no MW value and no flow animation. Do not draw per-line routes for blocks without lines.
- `persistent_value` records (currently `Java`) need a visible "unchanged value" treatment and no
  "live flow" animation.
- If the national residual is non-zero, show both numbers or neither; never silently rescale.
- No document or `publication != "authorized"`: production shows the existing national import/export
  aggregates or an unavailable state. Test fixtures must be labelled test-only.

## 7. Versioning

- Additive changes (new optional field) keep `v1`. Removing or redefining a field, the sign, the
  `source_id` scheme or the time semantics requires `cross_border_flow/v2`.
- `parser` changes whenever the parsing rules change; consumers can display it for provenance.

## 8. Open items (owner / source)

1. Written GSE permission (or terms) for automated retrieval and for **public redistribution of
   line-level records**. Until then: `publication = "not_authorized"`, no collection, no display.
2. Meaning of GSE codes (ACT, NRE, SUB, BLS) and why the RUSSIA subtotal is 0: requires GSE.
3. Whether `Java` is a substituted/blocked value: requires GSE.
4. Any map geometry: separate rights-cleared dataset plus security review.
