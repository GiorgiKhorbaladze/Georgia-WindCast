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
    Entry("ruisi", None, None, "unverified", "owner recollection: 206 MW, end of September or October 2026; "
          "first GSE balance value September 2026 (0.31 GWh); staged capacity not established"),
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
