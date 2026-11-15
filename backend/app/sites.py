"""Tracked wind farm locations.

Coordinates were verified on 2026-11-14 against attributable sources; see docs/sources/sites.md
for the full evidence and cross-checks. They are representative site points for requesting
meteorological model data, not turbine positions. Hub-height measurements are not available
and are never invented: model data is requested at the provider's standard heights.

No generation (MW) is associated with any site. GSE publishes the national total only.
"""

from __future__ import annotations

from app.schemas import SiteSummary

SITES: tuple[SiteSummary, ...] = (
    SiteSummary(
        id="ruisi",
        name_ka="რუისის ქარის ელექტროსადგური",
        name_en="Ruisi Wind Farm",
        coordinates_verified=True,
        latitude=42.055596,
        longitude=43.985914,
        municipality_en="Gori and Kareli municipalities",
        municipality_ka="გორისა და ქარელის მუნიციპალიტეტები",
        status_en="Under construction (206 MW, 33 turbines) per the latest sources",
        status_ka="მშენებარე (206 მგვტ, 33 ტურბინა) უახლესი წყაროების მიხედვით",
        coordinate_source=(
            "Wikidata Q141155401, citing the developer's wind farm layout document (windpower.ge)"
        ),
        coordinate_uncertainty_km=4.0,
        coordinate_note=(
            "Large site: TheWindPower lists a point 3.8 km west and Global Energy Monitor one "
            "1.9 km south. The point represents the farm, not a turbine."
        ),
    ),
    SiteSummary(
        id="zemo-wind",
        name_ka="ზემო ქარის ელექტროსადგური",
        name_en="Zemo Wind",
        coordinates_verified=True,
        latitude=41.895560,
        longitude=44.370612,
        municipality_en="Kaspi Municipality (Niabi)",
        municipality_ka="კასპის მუნიციპალიტეტი (ნიაბი)",
        status_en="Test operation reported from 2026 (18.75 MW, 3 turbines)",
        status_ka="2026 წლიდან საცდელ ექსპლუატაციაშია (18,75 მგვტ, 3 ტურბინა)",
        coordinate_source=(
            "Wikidata Q141149692, citing the Ministry of Environmental Protection and "
            "Agriculture screening decision for Zemo Wind LLC (ei.gov.ge)"
        ),
        coordinate_uncertainty_km=1.0,
        coordinate_note="Single primary source; no independent cross-check was available.",
    ),
    SiteSummary(
        id="kartli-gori",
        name_ka="ქართლის ქარის ელექტროსადგური",
        name_en="Kartli (Qartli) Wind Farm, Gori",
        coordinates_verified=True,
        latitude=42.022423,
        longitude=44.047890,
        municipality_en="Gori and Kareli municipalities",
        municipality_ka="გორისა და ქარელის მუნიციპალიტეტები",
        status_en="Operating since 2016 (20.7 MW, 6 turbines)",
        status_ka="ექსპლუატაციაშია 2016 წლიდან (20,7 მგვტ, 6 ტურბინა)",
        coordinate_source=(
            "Wikidata Q141149685, from OpenStreetMap relation 8371089 (Qartli Wind Farm)"
        ),
        coordinate_uncertainty_km=0.5,
        coordinate_note=(
            "Independent points from TheWindPower and Global Energy Monitor lie within 0.5 km."
        ),
    ),
)

SITES_BY_ID = {s.id: s for s in SITES}
