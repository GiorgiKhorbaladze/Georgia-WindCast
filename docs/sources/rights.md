# Source rights status (reviewed 21.11.2026)

Publicly reachable data is **not** treated as licensed for redistribution. This page records what
was verified, what was not, and which decisions belong to the owner. It is not legal advice.

## 1. GSE (Georgian State Electrosystem)

| Item | Status | Evidence |
|---|---|---|
| Written terms of use / data licence for the real-time XML | **Not found** | GSE site menu (`admin.gse.com.ge/api/en/menu`, 181 entries) has no terms-of-use or data-licence page. The documents titled "Terms and Conditions of Contract" are a procurement draft contract, a contractor confidentiality agreement and a privacy policy for `dispapp.gse.com.ge`; none covers reuse of public power-system data. |
| `robots.txt` | `gse.com.ge`: `Allow: /`; `admin.gse.com.ge`: `Disallow:` (empty) | Crawler etiquette only; **not a licence or permission**. |
| Copyright notice in the XML files | none | The files carry no copyright or licence statement. |
| Authorization for the current use | Handled by the owner | Correspondence with the source is kept outside this repository. |
| Line-level exchange records (`Intercha`/`IntchSum`) | **Not published** | Contract v1 (`docs/contracts/cross_border_flow_v1.md`) ships with `publication: "not_authorized"`; nothing collects or shows them. Enabling them is a separate owner decision. |
| Polling load | About 1,300 requests/day (PR #51) | GSE has published no rate limit. |

The project shows GSE national aggregates and the monthly balance documents with attribution to
GSE; line-level records stay unpublished (see above).

## 2. Open-Meteo (weather data)

| Item | Status |
|---|---|
| Data licence | CC BY 4.0: credit "Weather data by Open-Meteo.com" with a link to the licence, and indicate changes. |
| Free API terms | **Non-commercial use only**; limits under 10,000 calls/day, 5,000/hour, 600/minute. Commercial use needs a paid plan or self-hosting. |
| Current use | Collector: new ICON runs, 1 ERA5 and 1 historical-forecast request per day; forecasting (#62, after merge): one batched 7-point request per new ICON run; plus cached visitor-triggered app requests. Well within the limits. |
| UI attribution | "Open-Meteo (CC BY 4.0)" linked on the data page; model labels "DWD ICON global ... via Open-Meteo" and "ERA5". DWD and Copernicus credits are shown on the data page. |

**Owner decision needed (Open-Meteo):** confirm the project's use category is non-commercial. If
WindCast is used commercially, or within a commercial organisation's operations, a subscription is
required.

## 3. Upstream model data reached through Open-Meteo

- **DWD ICON:** Deutscher Wetterdienst open data, credit "Deutscher Wetterdienst (DWD)".
- **ERA5:** Copernicus Climate Change Service (C3S) / ECMWF. The Copernicus licence asks for the credit
  "Contains modified Copernicus Climate Change Service information [year]", without implying
  endorsement.

Both credits are on the data page's source links (KA/EN).

## 4. Map and other assets

Covered in `docs/sources/system-snapshot.md`: basemap (OpenFreeMap / OpenMapTiles / OpenStreetMap,
ODbL attribution) and the candidate GIS sources. **No transmission geometry is published**. Any
network GIS needs separate rights and a security review.

## 5. Summary of open decisions

1. Publication of line-level records (contract v1 gate), if ever wanted.
2. Open-Meteo use category confirmed as non-commercial.
3. Polling cadence: currently every 15 minutes (cron-job.org), about 1,300 requests/day.
