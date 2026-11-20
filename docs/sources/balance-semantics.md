# Balance figures: semantics and the published arithmetic difference (20.11.2026)

Evidence base: the `data` branch (5,547 stored wind/balance periods, 08.11-20.11.2026) and 84
authentic GSE files sampled 12.11-20.11 (analysis only; see `docs/contracts/cross_border_flow_v1.md`).

## Signs and units
- **Power:** all values are 3-minute average active power in MW (`P`, `MvAvr03m`). Energy (MWh) =
  sum × 0.05 h over stored periods only.
- **Ties:** positive = flow into Georgia (import), negative = out (export). Verified by exact
  closure in SUB-coded files (below).
- **Gross figures:** gross import = sum of positive tie flows, gross export = sum of |negative| flows,
  using individual lines where the block publishes them, otherwise the block subtotal (the RUSSIA
  subtotal reads 0 while its lines carry flow).

## Time
- A label marks the **end** of its 3-minute interval. Labels are stored in UTC; GSE file names and
  `period_label_local` are Tbilisi time (UTC+4, no DST).
- Wind, balance and ties come from the **same file**, so they always share one period. The app never
  mixes periods in one figure (tested in `test_system_snapshot.py`).

## Zero vs missing
- **No file** (HTTP 404 / not yet published) = no record for that period. It is never written as 0,
  and the app leaves a gap. GSE appears to retain files for about 10-12 days (scattered 404s on
  08-10.11 as of 20.11).
- **0.000000 in a file** = a published zero. Armenia's subtotal and the RUSSIA subtotal read 0 in all
  sampled files; Salkhino reads `-0.000000` (normalised to 0).

## Negative near-zero wind
- National wind occasionally reads slightly negative (minimum −0.18 MW), only at near-zero output.
  It is stored and shown as published. A plausible reading is station auxiliary consumption under
  net metering, but **GSE has not confirmed this**; values are not clipped.

## Quality codes
- Raw codes (ACT, NRE, SUB, BLS, INV) are kept in every record and in the CSV downloads, used
  internally (freshness "unconfirmed" state, revalidation), and not shown in the public UI (owner
  decision of 19.11.2026). Their meaning is unpublished and is not guessed.

## The published arithmetic difference
- **Definition:** `residual = (consumption − generation) − (sum of tie flows)`, all as published.
- **Observation (84 files):**
  - in all 35 files where `generation` and `consumption` carry code SUB, the residual is 0
    (< 0.01 MW);
  - in all 49 files where either carries NRE, it is non-zero (mean 9.15 MW, max 27.54 MW);
  - the archive shows the same pattern (owner audit of 18.11: up to ~50 MW when NRE-coded).
- **Interpretation limits:** the difference is a property of the published totals, coinciding
  exactly with the NRE code on the totals. It is **not** a measured physical system imbalance,
  network loss or unmetered flow, and the project does not label it as such. The original values
  are preserved unchanged; the app discloses the difference as a published difference.
- **Open:** cause and meaning of NRE on the totals, which requires GSE.

## Observation affecting displayed imports
- The `Java` line reported 18.299999 MW with code BLS in all 84 sampled files and is included in
  gross import, as in GSE's own arithmetic. When the other import flows are zero, the displayed
  national import (e.g. 18.3 MW on the live map at 20.11.2026 16:27 UTC) consists entirely of this
  persistent value. Whether to annotate or exclude it is an **owner decision** pending GSE's
  explanation; nothing has been changed.
