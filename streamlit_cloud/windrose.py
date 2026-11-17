"""Wind rose: frequency of wind FROM direction by speed band. Pure functions, no Streamlit.

- Direction: meteorological FROM convention, clockwise from north; sector i is centred on
  i * width (sector 0 = north, wrapping 359° and 1° into the same sector).
- Calm: speed below CALM_MS (Beaufort 0, < 0.5 m/s) has no meaningful direction; it is counted
  in the denominator and reported separately, not spread over sectors.
- Percentages: share of VALID hours (speed and direction both present). Hours with a missing
  speed or direction are excluded and counted.
- One plot = one source and one height; the caller never mixes sources, heights or vintages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

CALM_MS = 0.5
# Band edges in m/s. 3 m/s is close to a typical turbine cut-in speed and 12 m/s to a typical rated
# speed; 6 and 9 split the range in between. Upper band is open.
BAND_EDGES = (0.5, 3.0, 6.0, 9.0, 12.0)


def band_labels() -> list[str]:
    edges = list(BAND_EDGES)
    return [f"{a:g}-{b:g}" for a, b in zip(edges, edges[1:], strict=False)] + [f"≥{edges[-1]:g}"]


def sector_of(deg: float, sectors: int = 16) -> int:
    width = 360.0 / sectors
    return int(((deg % 360.0) + width / 2) // width) % sectors


def band_of(speed: float) -> int | None:
    """Index into band_labels(); None for calm."""
    if speed < CALM_MS:
        return None
    for i, hi in enumerate(BAND_EDGES[1:]):
        if speed < hi:
            return i
    return len(BAND_EDGES) - 1


@dataclass(frozen=True)
class Rose:
    table: pd.DataFrame  # index: sector centre (deg); columns: band labels; values: % of valid hours
    n_valid: int
    n_missing: int
    calm_pct: float
    first: pd.Timestamp | None
    last: pd.Timestamp | None
    sectors: int


def _valid(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def rose(values, sectors: int = 16) -> Rose:
    """values: iterable of objects with valid_at, speed_ms, direction_deg (one source, one height)."""
    if sectors not in (8, 16):
        raise ValueError("sectors must be 8 or 16")
    labels = band_labels()
    counts = [[0] * len(labels) for _ in range(sectors)]
    valid = missing = calm = 0
    times = []
    for v in values:
        times.append(v.valid_at)
        if not (_valid(v.speed_ms) and _valid(v.direction_deg)):
            missing += 1
            continue
        valid += 1
        b = band_of(float(v.speed_ms))
        if b is None:
            calm += 1
            continue
        counts[sector_of(float(v.direction_deg), sectors)][b] += 1
    width = 360.0 / sectors
    table = pd.DataFrame(counts, index=[i * width for i in range(sectors)], columns=labels, dtype=float)
    if valid:
        table = table / valid * 100.0
    return Rose(table=table, n_valid=valid, n_missing=missing, calm_pct=(calm / valid * 100.0) if valid else 0.0,
                first=min(times) if times else None, last=max(times) if times else None, sectors=sectors)
