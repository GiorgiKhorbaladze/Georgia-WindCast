# GSE national wind generation - source verification

Issue: #3. Evidence collected 2026-11-14 between 19:49 and 20:25 UTC (23:49-00:25 Tbilisi). Everything below was observed directly unless marked **inference** or **open**.

## 1. Outcome

| Item | Status |
| --- | --- |
| Original candidate `https://www.gse.com.ge/apps/gsebackend/rest/map`, field `typeSum.windPowerData` | **Not usable.** No longer an API (see 2). |
| Replacement source used by the current GSE website | **Verified technically**: 3-minute XML exports on `admin.gse.com.ge` (see 3). |
| Unit (MW) | Verified from GSE's own presentation; field name consistent (see 4). |
| Timestamp meaning | Label verified; whether it marks period end is **inference** (see 5). |
| Quality codes | Observed values recorded; meanings **open** (see 6). |
| Reuse / redistribution terms | **Open - blocker for enabling ingestion** (see 9). |

Ingestion is implemented and tested but ships **disabled** (`WINDCAST_GSE_INGESTION_ENABLED=false`) until the owner confirms the reuse terms.

## 2. The original candidate endpoint

- `GET https://www.gse.com.ge/apps/gsebackend/rest/map` → `301` to `https://gse.com.ge/apps/gsebackend/rest/map`.
- That URL → `200`, `content-type: text/html`, 3343 bytes, `last-modified: Fri, 06 Nov 2026 10:08:26 GMT`. The body is the single-page-application shell of the redesigned website (`<div id="root"></div>`), served for any unknown path.
- Consequence: an integration expecting JSON at this path would receive HTTP 200 with HTML. The new client therefore rejects any non-XML content type as `unexpected_content` (a failure with backoff), never as data.

## 3. The current source

The website's data hook (`/assets/useGseData-*.js`, `/assets/PowerGrid-*.js`, fetched 2026-11-14) builds file names from the current Tbilisi time floored to 3 minutes and fetches:

```
https://admin.gse.com.ge/storage/uploads/fact/GSE_EXPORT_NEW_PERIOD_03M_DDMMYYYY_HHMM.XML
```

It takes the block named `TOTAL WIND PLANTS` and sums `TA` rows with `EL='P'` and `IN='MvAvr03m'`. In every file observed that block holds exactly one row. A 1-minute export (`GSE_EXPORT_PERIOD_01M_…`) also exists, but it carries only system frequency.

Recorded example (`backend/tests/fixtures/gse/real_act_15112026_0009.xml`, unmodified):

```xml
<Export Time='15.11.2026 00:09:00' Period='03M' Type='Real Time Data'/>
<BLOCK_AREA Name='TOTAL WIND PLANTS                           '>
<TA B1='AllGeorg' B2='WindPP' B3=' ' EL='P' IN='MvAvr03m' VALUE='73.599297' QUALITY='ACT'/>
</BLOCK_AREA>
```

The same file also contains hydro, thermal, solar, total generation, tie-line and consumption blocks. WindCast reads only the wind block.

HTTP characteristics observed:

| Property | Observation |
| --- | --- |
| Content type | `text/xml`, encoding `ISO-8859-1`, about 2.3 KB |
| Caching | `Cache-Control: max-age=2592000`, strong `ETag`, `Last-Modified` per file. Published files behave as immutable. |
| Not yet published / missing | `404 text/html` (162 bytes) |
| Existence helper | `GET https://admin.gse.com.ge/api/file-exists?path=…` → `{"exists": true}` (not used by WindCast) |
| Authentication | None |

## 4. Unit

`MvAvr03m` reads as "MW, average over 3 minutes". GSE's own page renders the value with its `megaw` (MW) label. The magnitude (about 73-93 MW) is consistent with Georgia's installed wind capacity. Stored and exposed as MW, labelled as a 3-minute average.

## 5. Timestamps and cadence

- `Export Time` is local Tbilisi time (`DD.MM.YYYY HH:MM:SS`) and matches the file name (e.g. `…_15112026_0009.XML` ↔ `15.11.2026 00:09:00`). Asia/Tbilisi is UTC+4 with no daylight saving time, so the label converts to UTC without ambiguity. WindCast stores it in UTC (`period_label_at`) and keeps the raw local string (`period_label_local`).
- Cadence: one file every 3 minutes on the :00/:03/:06 grid.
- Publication lag (`Last-Modified` minus label): 77-78 s for most periods, 138 s for 00:15, and about 198 s for 00:00.
- **Inference:** the label marks the **end** of the averaging interval. Files appear after the label time, and the lag is shorter than 3 minutes. GSE has not confirmed this; the UI labels the value "3-minute average" with the GSE timestamp and does not claim a window.
- Retrieval time (`retrieved_at`) is stored separately and never substitutes for the source time.

## 6. Quality codes (open)

Observed on the wind row: `ACT` (most periods) and `NRE` (e.g. 00:03, 00:15 on 15.11.2026, and 00:12 on 14.11.2026). Other blocks also showed `SUB` and `BLS`. Their meanings are not published. WindCast stores the code verbatim, exposes it, and flags any code other than `ACT` in the UI. It does not discard or reinterpret such readings. **Owner action:** confirm the code semantics with GSE SCADA/IT, and decide whether a code such as `NRE` (possibly "not refreshed") should be treated as stale.

Also observed: the 00:09 and 00:12 periods (15.11.2026) carry the identical value `73.599297` with `ACT`. An exact repeat to six decimals may mean upstream telemetry was held or repeated. WindCast stores both as published and does not judge them. **Owner action:** ask GSE whether `ACT` guarantees a refreshed measurement.

## 7. Retention

| File label (Tbilisi) | Result |
| --- | --- |
| 14.11.2026 23:12 (1 h earlier) | 200 |
| 14.11.2026 00:12 (1 day) | 200 |
| 08.11.2026 00:12 (7 days) | 404 |
| 16.10.2026 00:12 (30 days) | 200 |
| 17.08.2026 00:12 (90 days) | 404 |
| 11.05.2026 10:54 (hard-coded fallback in GSE's site code) | 404 |

Retention is irregular. WindCast does **not** backfill from the archive. History starts when ingestion starts; within the last hour, the worker fetches published files it missed (for example after a restart). Missing periods stay visible as gaps.

## 8. Polling design

- Every `WINDCAST_GSE_POLL_SECONDS` (60 s), request only periods that are due (label + 75 s) and not stored, newest first, with at most 4 requests per tick. Steady state is about 1-2 requests per 3-minute period (roughly 500-1000 requests per day), each about 2.3 KB.
- A `404` means "not published yet" and is not a failure. After 3 misses an older period is abandoned and remains a gap; the newest period keeps being checked.
- Timeout, network error, `429`, `5xx`, unexpected content and schema drift count as failures: exponential backoff from 60 s up to 30 min with ±20% jitter. `Retry-After` (seconds or HTTP date) is honoured as a floor, capped at 1 hour. State is persisted in `source_status`.
- Writes are idempotent on `(source, metric, period_label_at)`. If GSE republishes a period with different bytes, the row is updated, `revision` is incremented, and a warning is logged.
- A failed poll never touches stored readings. Freshness is computed from the source label (`fresh` within 600 s), so a stale reading can never look refreshed.
- Strict parser (`defusedxml`, entity expansion forbidden). A missing or renamed block, duplicate rows, unexpected `Period`, bad time format, non-numeric or non-finite values, and values outside -50…2000 MW are all rejected.
- No `User-Agent` override by default. Operators may set `WINDCAST_GSE_USER_AGENT` to identify their deployment to GSE.

## 8a. Label and quality safeguards (issue #16)

- **Embedded label must match the request.** The `Export Time` inside a file must equal the period of the requested file name. Otherwise the payload is rejected as `label_mismatch` before anything is written, and counts as a failure with backoff.
- **No future labels.** A label more than 60 s ahead of this host's clock is rejected (`future_label`). The latest-reading and history queries also ignore any stored label later than now, so a bad row cannot become "latest".
- **Quality is not freshness.** A timely reading with a quality code other than `ACT` is reported as `unverified` with reason `quality_not_actual`. The published value and the raw code stay visible, but it is never shown with a plain "Fresh" badge.
- **Open pages expire.** The API returns `fresh_until`. The dashboard refreshes once a minute through the frontend (never GSE directly), expires the badge locally after `fresh_until`, and marks the kept value stale when a refresh fails.

## 9. Reuse terms (open - blocker)

No terms of use, licence or API policy covering these files were found on the public site during this check. The files are unauthenticated, are linked from the public homepage, and include no copyright statement. **That is not permission.** Before enabling ingestion for any deployment, the owner should confirm with GSE that automated retrieval at this rate and display with attribution are acceptable. The UI already credits "Georgian State Electrosystem (GSE)" with a link.

## 10. How to re-verify

```bash
cd backend && uv run python -m app.ingestion.live_check --periods 6
```

Alternatively, run the manual GitHub workflow **Live source check**, which is not part of CI. The check fetches the newest due files, parses them, prints the value, quality, label and age, and writes nothing.

Live run of this check, 2026-11-14 20:20:00 UTC: `GSE_EXPORT_NEW_PERIOD_03M_15112026_0018.XML` → 404 (not yet published); `…_0015.XML` → 200, 72.440331 MW, `NRE`, label 20:15:00 UTC, `Last-Modified` 20:17:18 UTC.
