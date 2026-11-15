# Wind farm site coordinates - verification

Issue: #4. Verified 2026-11-14. Coordinates are **representative site points** for requesting meteorological model data. They are not turbine positions, and no generation is associated with them. Distances were computed with the haversine formula.

| Site | Coordinate used (WGS 84) | Primary source | Cross-checks | Uncertainty used |
| --- | --- | --- | --- | --- |
| **Ruisi Wind Farm** (206 MW, 33 × Goldwind GWH171-6.25, under construction) | 42.055596, 43.985914 | Wikidata [Q141155401](https://www.wikidata.org/wiki/Q141155401), referencing the developer's *Ruisi Wind Power Plant Project - Wind Farm Layout Definition Procedure* (windpower.ge) | TheWindPower #30401: 42°03'25.2"N 43°56'23.2"E (42.05700, 43.93978), **3.81 km W**; Global Energy Monitor "Ruisi (Peri)": 42.0387, 43.9913, **1.93 km S** | ±4 km |
| **Zemo Wind** (18.75 MW, 3 × 6.25 MW, test operation 2026) | 41.895560, 44.370612 | Wikidata [Q141149692](https://www.wikidata.org/wiki/Q141149692), referencing the Ministry of Environmental Protection and Agriculture screening decision for Zemo Wind LLC's plant in Kaspi Municipality (ei.gov.ge); location item: Niabi | None available | ±1 km (single source) |
| **Kartli (Qartli) Wind Farm, Gori** (20.7 MW, 6 × Vestas V117-3.45, operating since 2016) | 42.022423, 44.047890 | Wikidata [Q141149685](https://www.wikidata.org/wiki/Q141149685), from OpenStreetMap relation [8371089](https://www.openstreetmap.org/relation/8371089) | TheWindPower #23805: 42°01'5.4"N 44°02'58.2"E (42.01817, 44.04950), **0.49 km**; Global Energy Monitor: 42.0270, 44.0460, **0.53 km** | ±0.5 km |

Separation between sites: Kartli-Ruisi 6.3 km, Kartli-Zemo 30.2 km.

## Notes and limitations

- **Ruisi** spreads over several kilometres. The three published points differ by up to 3.8 km. The developer-document point was chosen because it comes from the developer's own layout document. TheWindPower and GEM list Ruisi as under construction (TheWindPower, fetched 2026-11-14), and a GSE news item reports a visit to the "under-construction" plant in 2026. Its contribution to the GSE national total therefore depends on commissioning progress, which WindCast does not model.
- **Zemo Wind** has only one primary source (the government screening decision, via Wikidata). Independent databases (TheWindPower, GEM) had no usable point at the time of checking.
- **Hub heights** are not measured or used. Wikidata lists 105 m as the height of the Ruisi and Zemo turbines; for Kartli, 150 m (likely tip height). Model data is requested at the provider's standard heights (10/80/120/180 m forecast; 10/100 m reanalysis). The UI never labels any height "hub height".
- The Wikidata items are recent and carry detailed references. The cross-checks above come from sources independent of Wikidata.
- Sources not reachable from the verification environment (bm.ge, ei.gov.ge, www.gem.wiki) were not fetched directly. Their content is cited through the references above and search-engine summaries.
- **Georgian display names** (`backend/app/sites.py`) need owner confirmation.

## Model grid implications

- **ICON global** (forecast, 0.125°, about 13 km): verified with a real response on 2026-11-15. **Ruisi and Kartli both resolve to grid point (42.0, 44.0)**; Zemo Wind resolves to (41.875, 44.375).
- **ERA5** (reanalysis, 0.25°, about 25 km): Ruisi and Kartli again share the cell (42.0, 44.0); Zemo Wind is at (42.0, 44.25).
- Consequence: **the model values for Ruisi and Kartli are identical in both products.** The farms are only 6.3 km apart. The UI states this on the forecast and map pages, and tests document it. The API reports the grid point used for every series (`grid_latitude/longitude/elevation_m`). A finer model would distinguish them, for example ICON-EU at about 7 km. But ICON-EU's intermediate runs reach only about 30 h, so a guaranteed 72 h horizon would need run selection logic. This is listed as an improvement option for the owner.
