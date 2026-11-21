# System Map & Live System Snapshot

The System map uses a local Streamlit component to place the national wind reading, trend and latest-period controls over an interactive geographic map. Streamlit refreshes the component's data every three minutes. Pan, zoom, fullscreen and playback run in the browser. The component reads the existing balance archive through the same shared reader as **Power system balance** and makes no upstream API or tile requests.

## National readings and playback

- **Consumption, total generation, hydro, thermal, wind and solar** come from the corresponding national blocks in one GSE three-minute XML export. **Import and export** are the collector's gross national totals from the same period. Values represent average power in **MW**. The reported wind figure is national and has no connection to any wind-site marker.
- The source label and collector retrieval time are shown separately in Tbilisi time. A source label more than ten minutes old is stale. A recent period with missing or non-ACT quality metadata in any of the six national blocks, or a failed refresh, has unconfirmed quality. Raw quality metadata and payload hashes are retained in the archive and excluded from component messages.
- Zero displays as zero. Missing readings display as a dash. The signed balance residual is generation + imports − exports − consumption, calculated from unrounded values. The interface labels this as a difference between published balance figures and explains that a physical imbalance requires separate measurements. A nonzero difference is retained, and a missing term leaves the check unavailable.
- The trend breaks at gaps. The comparison appears only when both wind readings are present, their quality passes the existing ACT check, and their source labels are exactly three minutes apart. The playback slider selects actual stored periods within the preceding 24 hours. Historical playback is labeled explicitly, skips missing timestamps without filling data, and updates all cards together. Speed changes the presentation interval, independent of the source cadence. **Latest** returns to the refreshed view.
- Frequency remains out of scope. The separate one-minute GSE export requires a source and permission review before collection.

## What the authorized tie-line fixtures establish

The [recorded GSE fixtures](../../backend/tests/fixtures/gse) use `B1=AllGeorg`, `EL=P` and `IN=MvAvr03m`. Within tie-line blocks, `B2=Intercha` identifies an individual row and `B2=IntchSum` a subtotal. `B3` carries source identifiers. The tests verify that the signed values used by the existing collector reconcile to the stored gross totals. Positive means into Georgia and negative means out of Georgia. The collector uses individual rows where present and falls back to that block's subtotal where they are absent. Adding both would double-count some blocks.

The two fixtures label Azerbaijan, Armenia, and Turkey through subtotals only. The Russia block contains a zero subtotal and the individual identifiers `Salkhino`, `Java`, and `Nakaduli`. These strings do not verify endpoints or country assignments beyond source block membership. An individual row has a non-ACT quality flag and some subtotal entries are missing individual measurements. The 00:03 Tbilisi fixture also has a −12.512113 MW residual. The source flags and mismatch do not establish a cause by themselves. An offline diagnostic exposes source label, raw block/identifier, row kind, signed MW and quality for reconciliation.

The public archive has no per-line history, independent mapping of GSE identifiers, or comparable per-flow quality fields. Imports and exports panels therefore show national gross totals and say that line-level readings are unavailable. No route, endpoint, line-specific measurement, geographic or schematic flow animation is displayed. No ingestion, archive schema or scheduled workflow was expanded.

If approved line-level collection and independently verified geometry become available, animate only time-qualified, validated directional readings. The motion rate would be illustrative and would have no physical meaning. Historical animation would require actual archived line records for the selected period.

See the [pinned archive reconciliation and original XML evidence](../evidence/premium-system-map/reconciliation.md) for audited periods, the reproduced statistics and source access limits.

## Release and data acquisition gates

Source authorization is handled by the owner (see `docs/sources/rights.md`). This page uses the same archive and activates no additional collection or publication.

Before a line-level phase, get written approval for public line readings and independently reusable geometry. Define a reviewed registry mapping stable source identifiers to named interconnections and neighboring countries. Establish source completeness and quality semantics, including how absent, substituted, duplicate and subtotal-only records are handled. Persist per-line records separately from the existing backwards-compatible national series, with source period, signed MW, quality, source revision and provenance. Reconcile each archived period, preserve discrepancies, and publish animation only for approved, geographically corroborated lines with confirmed readings. Historic periods without line records must remain empty.

## Browser behavior

The renderer uses bundled SVG and small HTML overlays. It requires neither WebGL nor GPU acceleration. The explicit fullscreen button requests native browser fullscreen when the frame is allowed to do so. Otherwise a same-origin Streamlit frame expands to the viewport. Both retain the camera and playback selection. The exit button restores the previous page, and Escape exits the immersive fallback or is handled by the browser in native mode. The renderer has no required motion or background animation loop.

## Bundled geographic layers

| Layer | Source and vintage | Reuse and limits |
| --- | --- | --- |
| Georgia outline | [Natural Earth 1:10m Admin 0 countries, v5.1.2](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_10m_admin_0_countries.geojson), feature `ADM0_A3=GEO` | [Public domain](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/README.md). Bundled geometry retains the release's de facto boundary convention and cartographic generalization. |
| Reference cities | [Natural Earth 1:10m populated places, v5.1.2](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_10m_populated_places.geojson), four selected points with localized labels | Public domain. Coordinates represent cities at map scale. |
| Wind sites | The three existing [verified WindCast locations](sites.md), checked on 14 November 2026 | The same representative points and source uncertainties already used by WindCast. Use the focus selector to see uncertainty and provenance. |

All geography is bundled. Wind-site details open on click, touch or keyboard activation. The outline and city positions provide geographic context; they do not establish transmission geography.

## Transmission dataset gap and acquisition options

The 19 November 2026 source review did not establish a reusable operator-verified GIS layer for Georgia's **110, 220, 330, 400 or 500 kV** corridors, substations or additional generating assets. The PR includes no transmission geometries, regional measurements, switching status or new operating data.

| Candidate | What it establishes | What remains unverified |
| --- | --- | --- |
| [Georgian State Electrosystem](https://www.gse.com.ge/) public network presentation and supplied screenshots | Operator reference for the categories and map interactions the owner asked for | Dated georeferenced paths and nodes, an explicit redistribution grant, and the voltage and completeness of any machine-readable dataset. Screenshots cannot establish line alignment. |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) and [Open Infrastructure Map](https://github.com/openinframap/openinframap) | Community-mapped infrastructure and an OSM-based visualization. OSM's ODbL gives a reuse path with attribution and applicable database share-alike obligations. | No dated Georgian extract was validated against operator records in this review. Route alignment, voltage tags, missing assets and an attribution/distribution plan would need verification. Open Infrastructure Map does not provide an independent operator cross-check. |
| [ENTSO-E transmission map](https://www.entsoe.eu/data/map/) | Candidate for comparison with operator references | Georgian voltage coverage, surveyed versus schematic geometry, vintage and redistribution rights for a usable GIS extract were not verified. |

| [WRI Global Power Plant Database](https://github.com/wri/global-power-plant-database) | A georeferenced generating-site candidate, v1.3.0, CC BY 4.0 | Unmaintained since early 2022. WRI warns that record matching can misplace plants. Georgian plant locations and their current scope were not independently confirmed. It provides no grid routes or substation data. |

This cloud environment could read upstream projects on GitHub but refused direct connections to the GSE, Geofabrik, OSM and ENTSO-E hosts during the review. This limits the findings to the evidence above. No GSE map assets were copied.

**Owner decision for a separate acquisition.** The preferred route is to ask GSE for a dated GIS export with declared voltage, coordinate system, coverage, and written permission to republish the approved reference assets. If unavailable, a dated OSM subset could be evaluated against operator documentation after the owner approves acquisition and an ODbL distribution plan. Publish only corroborated, approved features as static reference infrastructure, with provenance and coverage gaps visible.
