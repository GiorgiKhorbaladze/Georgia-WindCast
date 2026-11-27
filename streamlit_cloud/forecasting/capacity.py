"""Wind fleet capacity by effective date (Issue #57). Capacity-factor models need it; MW models do not.

Only an entry with ``status == "verified"`` (an official public source with a URL) may be used as a
denominator. Owner-supplied or press figures stay ``unverified`` and switch capacity-factor
models off for every period they would cover.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

REGISTRY_VERSION = "capacity/1"


@dataclass(frozen=True)
class Entry:
    station_id: str
    effective_from: date | None  # None: commissioning date not established
    mw: float | None
    status: str  # "verified" | "unverified"
    source: str


ENTRIES: tuple[Entry, ...] = (
    Entry("kartli-gori", date(2016, 10, 1), 20.7, "unverified", "owner-supplied starting value; official source pending"),
    Entry("zemo-wind", date(2026, 3, 1), 18.75, "unverified", "owner-supplied starting value; first GSE balance month 2026-03"),
    Entry("ruisi", date(2026, 9, 24), None, "unverified",
          "owner-supplied 27.11.2026: entered the test phase and started generating on 24-27 September 2026; "
          "per the owner, a qualified enterprise has a 90-day test phase, i.e. until about 23-26 December 2026 "
          "(output during testing may be irregular). Capacity: secondary sources only, 33 x Goldwind GW171-6.25 MW "
          "= 206.25 MW (renews.biz, windtech-international.com); press 29.09.2026: launched in test mode "
          "(caspianpost.com, news.az); first GSE balance value September 2026 (0.31 GWh). No official document yet "
          "for the commissioning date or the capacity available during testing, so the entry stays unverified"),
)


def available_mw(day: date) -> float | None:
    """Verified fleet capacity on a day, or None when any operating station is unverified."""
    total = 0.0
    for e in ENTRIES:
        if e.effective_from is not None and e.effective_from > day:
            continue
        if e.status != "verified" or e.mw is None or e.effective_from is None:
            return None
        total += e.mw
    return total


def capacity_factor_enabled(day: date) -> bool:
    return available_mw(day) is not None
