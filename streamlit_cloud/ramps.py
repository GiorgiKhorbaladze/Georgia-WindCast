"""National wind-generation ramps from the GSE 3-minute aggregate. Pure functions, no Streamlit.

Definitions (shown to the user):
- A label marks the END of its 3-minute interval (GSE convention), stored in UTC.
- Ramp over horizon H at label t: value(t) - value(t - H), in MW. Both endpoints must be STORED
  periods with exactly those labels; nothing is interpolated, resampled or carried forward, so a
  missing endpoint means no ramp for that window.
- Windows overlap: one window ends at every 3-minute label (a 1 h ramp is evaluated every 3 min).
- Completeness = windows with both endpoints stored / windows whose both endpoints lie inside the
  selected range on the 3-minute grid.
- Quality: by default every stored value is used, as published; with act_only=True a window counts
  only if BOTH endpoints carry the code ACT. The meaning of other codes is not confirmed, so this
  is a sensitivity option, not a correction.
- MW/min = ramp / H in minutes (the average rate over the window, not an instantaneous rate).
These are descriptive historical statistics: not a forecast, not an imbalance volume and not a
regulating-reserve requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

PERIOD = pd.Timedelta(minutes=3)
HORIZONS = {"15min": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "3h": pd.Timedelta(hours=3)}


def deltas(df: pd.DataFrame, horizon: pd.Timedelta, start: pd.Timestamp | None = None,
           end: pd.Timestamp | None = None, act_only: bool = False) -> pd.DataFrame:
    """Signed ramps for every window whose endpoints are both stored.

    df: index = UTC end-of-interval labels, columns value_mw, quality.
    Returns columns: start_label, delta_mw, mw_per_min, q_start, q_end (index = end label).
    """
    if horizon <= pd.Timedelta(0) or horizon % PERIOD:
        raise ValueError("horizon must be a positive multiple of 3 minutes")
    cols = ["start_label", "delta_mw", "mw_per_min", "q_start", "q_end"]
    if df is None or not len(df):
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"))
    part = df
    if start is not None:
        part = part[part.index >= start]
    if end is not None:
        part = part[part.index <= end]
    starts = part.index - horizon
    prev = part.reindex(starts)  # exact label lookup: a missing endpoint stays NaN
    ok = prev["value_mw"].notna().to_numpy() & part["value_mw"].notna().to_numpy()
    out = pd.DataFrame({
        "start_label": starts,
        "delta_mw": part["value_mw"].to_numpy() - prev["value_mw"].to_numpy(),
        "q_start": prev["quality"].to_numpy(),
        "q_end": part["quality"].to_numpy(),
    }, index=part.index)
    out = out[ok]
    if start is not None:  # the start endpoint must also lie in the selected range
        out = out[out["start_label"] >= start]
    if act_only:
        out = out[(out["q_start"] == "ACT") & (out["q_end"] == "ACT")]
    out["mw_per_min"] = out["delta_mw"] / (horizon / pd.Timedelta(minutes=1))
    return out[cols]


def possible_windows(start: pd.Timestamp, end: pd.Timestamp, horizon: pd.Timedelta) -> int:
    """Windows on the 3-minute grid with both endpoints inside [start, end]."""
    first = start.ceil("3min")
    last = end.floor("3min")
    span = last - first - horizon
    return 0 if span < pd.Timedelta(0) else int(span / PERIOD) + 1


@dataclass(frozen=True)
class RampStats:
    n: int
    possible: int
    max_up: float | None
    max_up_end: pd.Timestamp | None
    max_down: float | None
    max_down_end: pd.Timestamp | None
    p95_abs: float | None
    share_up: float | None  # share of windows with an increase (> 0)

    @property
    def completeness(self) -> float:
        return self.n / self.possible if self.possible else 0.0


def stats(d: pd.DataFrame, possible: int) -> RampStats:
    """Extremes (with their window end labels), 95th percentile of |ramp| and share of increases."""
    if d is None or d.empty:
        return RampStats(0, possible, None, None, None, None, None, None)
    up_i, down_i = d["delta_mw"].idxmax(), d["delta_mw"].idxmin()
    up, down = float(d.loc[up_i, "delta_mw"]), float(d.loc[down_i, "delta_mw"])
    return RampStats(
        n=int(len(d)), possible=possible,
        max_up=up if up > 0 else None, max_up_end=up_i if up > 0 else None,
        max_down=down if down < 0 else None, max_down_end=down_i if down < 0 else None,
        p95_abs=float(d["delta_mw"].abs().quantile(0.95)),
        share_up=float((d["delta_mw"] > 0).mean()),
    )
