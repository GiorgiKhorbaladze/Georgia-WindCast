"""Forecast accuracy of the archived ICON runs. Pure functions.

No anemometer measurements exist for the sites, so the forecast is verified against reference data
that is itself model-based, and the UI says so:
- "analysis": for each valid hour, the value of the most recent LATER run at a lead under 6 h
  (short-range forecast as best available estimate; it shares the model's own biases);
- "era5": ECMWF ERA5 reanalysis at 10 m (independent model; about 25 km; 5-day lag).
Sites that fall in the same model grid cell get identical model values (Ruisi and Kartli share
one ICON and one ERA5 cell); aggregate scores count each cell once (independent()).
Errors are forecast minus reference. Direction errors are circular and use only hours with
reference speed >= 3 m/s (direction is meaningless at calm).
"""

from __future__ import annotations

import math
from datetime import timedelta

import pandas as pd

LEAD_BUCKETS = ((0, 6, "≤6h"), (6, 12, "6-12h"), (12, 24, "12-24h"), (24, 48, "24-48h"), (48, 72, "48-72h"))
ANALYSIS_MAX_LEAD = timedelta(hours=6)
DIRECTION_MIN_SPEED = 3.0


def _bucket(lead_h: float) -> str | None:
    for lo, hi, name in LEAD_BUCKETS:
        if lo < lead_h <= hi:
            return name
    return None


def analysis_reference(packets: list[dict]) -> dict:
    """(site, height, valid) -> (speed, direction, run) from the latest run with lead < 6 h."""
    ref: dict = {}
    for p in sorted(packets, key=lambda p: p["run"]):
        for i, loc in enumerate(p["series"]):
            for h, values in loc.by_height.items():
                for v in values:
                    if timedelta(0) <= v.valid_at - p["run"] < ANALYSIS_MAX_LEAD and v.speed_ms is not None:
                        ref[(i, h, v.valid_at)] = (v.speed_ms, v.direction_deg, p["run"])
    return ref


def era5_reference(archive: dict | None) -> dict:
    """(site, 10, valid) -> (speed, direction, None) from an ERA5 packet (10 m only)."""
    ref: dict = {}
    if not archive:
        return ref
    for i, loc in enumerate(archive["series"]):
        for v in loc.by_height.get(10, []):
            if v.speed_ms is not None:
                ref[(i, 10, v.valid_at)] = (v.speed_ms, v.direction_deg, None)
    return ref


def _cell(loc, i: int) -> tuple:
    """Model grid cell of a location series (falls back to the site index if no grid is known)."""
    lat, lon = getattr(loc, "grid_latitude", None), getattr(loc, "grid_longitude", None)
    return (round(lat, 4), round(lon, 4)) if lat is not None and lon is not None else ("site", i)


def pairs(packets: list[dict], ref: dict) -> pd.DataFrame:
    """Forecast/reference pairs; the reference must come from a later run (never the same one)."""
    rows = []
    for p in packets:
        for i, loc in enumerate(p["series"]):
            for h, values in loc.by_height.items():
                for v in values:
                    lead = (v.valid_at - p["run"]).total_seconds() / 3600
                    bucket = _bucket(lead)
                    r = ref.get((i, h, v.valid_at))
                    if bucket is None or r is None or v.speed_ms is None:
                        continue
                    if r[2] is not None and r[2] <= p["run"]:
                        continue
                    rows.append(dict(site=i, cell=_cell(loc, i), height=h, lead=bucket, valid=v.valid_at, run=p["run"],
                                     f_speed=v.speed_ms, r_speed=r[0], f_dir=v.direction_deg, r_dir=r[1]))
    return pd.DataFrame(rows)


def independent(df: pd.DataFrame) -> pd.DataFrame:
    """One pair per grid cell, height, run and valid hour: sites sharing a cell are not counted twice."""
    if df.empty or "cell" not in df:
        return df
    return df.drop_duplicates(subset=["cell", "height", "run", "valid"], keep="first")


def _circ(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    d = abs(a - b) % 360
    return min(d, 360 - d)


def scores(df: pd.DataFrame, by=("site", "height", "lead")) -> pd.DataFrame:
    """MAE, RMSE, bias (m/s) and circular direction MAE (deg) per group, with pair counts."""
    if df.empty:
        return pd.DataFrame(columns=[*by, "n", "mae", "rmse", "bias", "dir_mae", "dir_n"])
    d = df.copy()
    d["err"] = d["f_speed"] - d["r_speed"]
    d["dir_err"] = [
        _circ(f, r) if rs >= DIRECTION_MIN_SPEED else None
        for f, r, rs in zip(d["f_dir"], d["r_dir"], d["r_speed"], strict=True)
    ]
    out = []
    for key, g in d.groupby(list(by), sort=True):
        dirs = g["dir_err"].dropna()
        out.append(dict(zip(by, key if isinstance(key, tuple) else (key,), strict=True),
                        n=len(g), mae=float(g["err"].abs().mean()),
                        rmse=float(math.sqrt((g["err"] ** 2).mean())), bias=float(g["err"].mean()),
                        dir_mae=float(dirs.mean()) if len(dirs) else None, dir_n=int(len(dirs))))
    order = {name: k for k, (_, _, name) in enumerate(LEAD_BUCKETS)}
    res = pd.DataFrame(out)
    if "lead" in res:
        res = res.sort_values([c for c in by if c != "lead"] + ["lead"], key=lambda s: s.map(order) if s.name == "lead" else s)
    return res.reset_index(drop=True)
