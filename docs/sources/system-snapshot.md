# System Map & Live System Snapshot

The Streamlit **System map** refreshes every three minutes. It reads the newest available period in the past 24 hours from `balance/YYYY/MM/YYYY-MM-DD.csv` through the same history reader as **Power system balance**. The page makes no direct requests to GSE, weather services or map tile servers.

## National readings

- **Consumption, total generation, hydro, thermal, wind and solar** come from the matching national blocks in the GSE three-minute XML export. All cards show average power in MW for one source period. The collector retains full source precision and the cards display two decimals.
- **Import and export** are separate gross national totals from the existing [balance parser](../../streamlit_cloud/balance.py), based on the signed tie-line readings in that same export. A missing gross value is unavailable. Net interchange does not determine gross flows.
- The GSE source label and collector retrieval timestamp are separately identified in Tbilisi time. A source label over ten minutes old is stale. When a recent period has missing or non-ACT quality metadata in any of the six national blocks, or a refresh failed, the page treats its quality as unconfirmed. Even a recent label does not establish measurement accuracy. Quality codes, parser version and payload hash stay in the data branch. The balance record has no comparable per-flow quality metadata for gross interchange.
- Zero remains a recorded value. Missing or non-finite values show a dash and **Unavailable**. When no period is available in the past 24 hours, the map stays usable.
- **Phase 2 — frequency.** GSE publishes frequency in a separate one-minute export. Frequency is hidden pending a source reliability and reuse review and owner approval for any collection.

The cards are periodically refreshed national aggregates. The geographic layers are static reference data. See [GSE source verification](gse.md) and the [Streamlit pipeline](../../streamlit_cloud/README.md).

## Bundled geographic layers

| Layer | Source and vintage | Reuse and limits |
| --- | --- | --- |
| Georgia outline | [Natural Earth 1:10m Admin 0 countries, v5.1.2](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_10m_admin_0_countries.geojson), feature `ADM0_A3=GEO` | [Public domain](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/README.md). Bundled geometry retains the release's de facto boundary convention and cartographic generalization. |
| Reference cities | [Natural Earth 1:10m populated places, v5.1.2](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_10m_populated_places.geojson), four selected points with localized labels | Public domain. Coordinates represent cities at map scale. |
| Wind sites | The three existing [verified WindCast locations](sites.md), checked on 14 November 2026 | The same representative points and source uncertainties already used by WindCast. Use the focus selector to see uncertainty and provenance. |

All layers are available offline after the application loads. The interactive map requires browser WebGL. The named focus selector and site details are accessible without map hover.

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
