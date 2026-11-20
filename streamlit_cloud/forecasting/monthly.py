"""Monthly energy outlook architecture (Issue #57): per-station seasonal baseline with quantiles.

Input: the monthly archive (``wind_history``; official or owner-compiled records, never pending).
Each station is forecast from its own history of the same calendar month; a fleet total is
given only when every station expected to operate has enough comparable years. A changing fleet
is never treated as one stationary series. Q10/Q50/Q90 are empirical quantiles of past
same-month values (distribution quantiles, not project-finance P90s).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_YEARS = 5


@dataclass(frozen=True)
class Outlook:
    station_id: str
    year: int
    month: int
    q10: float | None
    q50: float | None
    q90: float | None
    years_used: int
    status: str  # "ok" | "insufficient_history"


def station_outlook(records, station_id: str, year: int, month: int) -> Outlook:
    own = [r for r in records if r.station_id == station_id]
    if not own:
        return Outlook(station_id, year, month, None, None, None, 0, "insufficient_history")
    first_year, first_month = min((r.year, r.month) for r in own)
    skip = first_year if first_month != 1 else None  # commissioning year is partial: not comparable
    past = sorted(r.energy for r in own if r.month == month and r.year < year and r.year != skip)
    if len(past) < MIN_YEARS:
        return Outlook(station_id, year, month, None, None, None, len(past), "insufficient_history")
    q10, q50, q90 = (float(x) for x in np.quantile(past, [0.1, 0.5, 0.9]))
    return Outlook(station_id, year, month, q10, q50, q90, len(past), "ok")


def fleet_outlook(records, stations: list[str], year: int, month: int) -> dict:
    parts = [station_outlook(records, s, year, month) for s in stations]
    complete = all(p.status == "ok" for p in parts)
    return dict(year=year, month=month, stations=[p.__dict__ for p in parts],
                fleet_q50_gwh=sum(p.q50 for p in parts) if complete else None,
                status="ok" if complete else "insufficient_history")
