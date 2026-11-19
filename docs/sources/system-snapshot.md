# System Map & Live System Snapshot

The Streamlit **System map** page refreshes every three minutes. It reads the newest available period in the past 24 hours from the existing `balance/YYYY/MM/YYYY-MM-DD.csv` collector output. It uses the same shared reader and cache as the Power system balance page. This page makes no direct requests to GSE or the weather APIs.

## National readings

- **Consumption, total generation, hydro, thermal, wind and solar** come from the corresponding national blocks in the GSE three-minute XML export. The cards display average power in MW from a single period. The collector retains the full source precision and the cards display two decimals.
- **Import and export** are the existing parser's separate gross national totals in MW, derived from the signed tie-line values using the method in [the balance parser](../../streamlit_cloud/balance.py). Older records may lack these fields. The page leaves such values unavailable because net interchange cannot determine gross flows.
- **System frequency** is unavailable in this page. GSE publishes frequency separately in the one-minute export and the existing balance pipeline does not collect it.
- The displayed source time is GSE's original Tbilisi label. Retrieval time comes from the collector record and is shown separately. The snapshot is marked stale once the source timestamp is more than ten minutes old. A recent timestamp describes recency only. The stored quality codes, parser version and payload hash remain in the existing data branch.
- Zero is a recorded value. Missing or non-finite values use a dash and an **Unavailable** label. The same label appears when there is no balance record in the preceding 24 hours. A failed refresh is indicated separately and a cached record still ages from its source timestamp.

See [GSE source verification](gse.md) and the [Streamlit data pipeline](../../streamlit_cloud/README.md) for source conventions, cadence and collection limitations.

## Map coverage

The map uses the three [verified representative wind farm locations](sites.md) and the public-domain [Natural Earth 1:10m Admin 0 country outline, v5.1.2](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_10m_admin_0_countries.geojson) (feature `ADM0_A3=GEO`). The bundled geometry is unchanged from that feature and follows Natural Earth's de facto boundary convention. It serves as geographic context for the representative points. The map requires browser WebGL. It loads no external tiles, and the site names remain available as text. GSE presentation screenshots are functional references for the national readings only. The repository has no verified transmission geometry or live asset-status data, so map markers carry no lines, substations, regional flows or current operational status.
