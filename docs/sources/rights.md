# Source rights status (reviewed 20.11.2026)

Publicly reachable data is **not** treated as licensed for redistribution. This page records what
was verified, what was not, and which decisions belong to the owner. It is not legal advice.

## 1. GSE (Georgian State Electrosystem)

| Item | Status | Evidence |
|---|---|---|
| Written terms of use / data licence for the real-time XML | **Not found** | GSE site menu (`admin.gse.com.ge/api/en/menu`, 181 entries) has no terms-of-use or data-licence page. The documents titled "Terms and Conditions of Contract" are a procurement draft contract, a contractor confidentiality agreement and a privacy policy for `dispapp.gse.com.ge`; none covers reuse of public power-system data. |
| `robots.txt` | `gse.com.ge`: `Allow: /`; `admin.gse.com.ge`: `Disallow:` (empty) | Crawler etiquette only; **not a licence or permission**. |
| Copyright notice in the XML files | none | The files carry no copyright or licence statement. |
| Existing authorization | **Owner-reported** for the current aggregate use (Streamlit README, Issue #18) | Not a written GSE document in this repository; its scope (automated polling rate, public redistribution, archive, line-level records) is not recorded. |
| Line-level exchange records (`Intercha`/`IntchSum`) | **Not authorized for publication** | Contract v1 (`docs/contracts/cross_border_flow_v1.md`) ships with `publication: "not_authorized"`; nothing collects or shows them. |
| Polling load | ~4,700 requests/day since the 15-minute trigger; PR #51 reduces it to about 1,300/day | See PR #51. The documented envelope is 500-1000/day; GSE has published no rate limit. |

**Owner decision needed (GSE):** obtain written confirmation from GSE (contact listed on the site:
`info@gse.com.ge`) covering:
1. automated retrieval of the 3-minute files at the actual rate;
2. public display and a public archive of the national aggregates (wind, balance, import/export);
3. publication of line-level records, if wanted;
4. the required attribution wording.

If the owner is professionally connected to GSE, any internal approval needed for a personal
public project is also the owner's decision. This review does not assume either way.

## 2. Open-Meteo (weather data)

| Item | Status |
|---|---|
| Data licence | CC BY 4.0: credit "Weather data by Open-Meteo.com" with a link to the licence, and indicate changes. |
| Free API terms | **Non-commercial use only**; limits under 10,000 calls/day, 5,000/hour, 600/minute. Commercial use needs a paid plan or self-hosting. |
| Current use | About 1-2 forecast runs plus 1 ERA5 request per day from the collector, plus visitor-triggered app requests (cached). Within the limits. |
| UI attribution | "Open-Meteo (CC BY 4.0)" linked on the data page; model labels "DWD ICON global ... via Open-Meteo" and "ERA5". This PR adds explicit DWD and Copernicus credits. |

**Owner decision needed (Open-Meteo):** confirm the project's use category is non-commercial. If
WindCast is used commercially, or within a commercial organisation's operations, a subscription is
required.

## 3. Upstream model data reached through Open-Meteo

- **DWD ICON:** Deutscher Wetterdienst open data, credit "Deutscher Wetterdienst (DWD)".
- **ERA5:** Copernicus Climate Change Service (C3S) / ECMWF. The Copernicus licence asks for the credit
  "Contains modified Copernicus Climate Change Service information [year]", without implying
  endorsement.

Added in this PR to the data page's source links (KA/EN).

## 4. Map and other assets

Covered in `docs/sources/system-snapshot.md`: basemap (OpenFreeMap / OpenMapTiles / OpenStreetMap,
ODbL attribution) and the candidate GIS sources. **No transmission geometry is published**. Any
network GIS needs separate rights and a security review.

## 5. Summary of open decisions

1. GSE written terms for retrieval, public archive and attribution (P0 for public release).
2. GSE permission for line-level records (gate for contract v1 publication).
3. Open-Meteo use category confirmed as non-commercial.
4. Whether to keep polling every 15 minutes (cron-job.org) once GSE states its view on load.
