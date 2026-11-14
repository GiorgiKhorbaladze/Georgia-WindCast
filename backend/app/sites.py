"""Tracked wind farm locations.

Coordinates are intentionally absent until verified against attributable sources under
issue #4. Model weather must never be requested for a guessed coordinate.
"""

from __future__ import annotations

from app.schemas import SiteSummary

SITES: tuple[SiteSummary, ...] = (
    SiteSummary(
        id="ruisi",
        name_ka="რუისის ქარის ელექტროსადგური",
        name_en="Ruisi Wind Farm",
        coordinates_verified=False,
    ),
    SiteSummary(
        id="zemo-wind", name_ka="ზემო ქარი", name_en="Zemo Wind", coordinates_verified=False
    ),
    SiteSummary(
        id="kartli-gori",
        name_ka="ქართლის (გორის) ქარის ელექტროსადგური",
        name_en="Kartli/Gori Wind Farm",
        coordinates_verified=False,
    ),
)
