"""Observed GSE national wind generation aggregated to forecast intervals (no gap filling).

Input: 3-minute GSE values (label = end of period, MW). Output per interval [start, end):
mean MW over the stored periods, the number stored, the number expected and completeness.
Daily energy MWh = sum(P_i) x 0.05 h over stored periods, reported only with its completeness;
an incomplete day is flagged, never scaled up or filled.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from forecasting.contract import CADENCES, GSE_PERIOD

PERIOD_HOURS = GSE_PERIOD.total_seconds() / 3600  # 0.05 h


def series(records) -> pd.Series:
    """GSE store records -> MW series indexed by UTC label (raw values kept, also negatives)."""
    s = pd.Series({r.period_label_utc: r.value_mw for r in records}, dtype=float)
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


def intervals(s: pd.Series, cadence: str) -> pd.DataFrame:
    """Columns mean_mw, n, expected, complete; index = interval start (UTC)."""
    step = CADENCES[cadence]
    expected = int(step / GSE_PERIOD)
    if s.empty:
        return pd.DataFrame(columns=["mean_mw", "n", "expected", "complete"])
    start = (s.index - GSE_PERIOD).floor(pd.Timedelta(step))
    g = s.groupby(start)
    out = g.agg(["mean", "size"]).rename(columns={"mean": "mean_mw", "size": "n"})
    out["expected"] = expected
    out["complete"] = out["n"] == expected
    return out


def actual_for(s: pd.Series, valid_from: datetime, valid_to: datetime) -> tuple[float | None, int, int]:
    """Mean MW of GSE labels in (valid_from, valid_to]; (None, 0, expected) if nothing stored."""
    expected = int((valid_to - valid_from) / GSE_PERIOD)
    sel = s[(s.index > valid_from) & (s.index <= valid_to)]
    return (float(sel.mean()) if len(sel) else None), len(sel), expected


def daily_energy(s: pd.Series, tz: str = "Asia/Tbilisi") -> pd.DataFrame:
    """Local-day energy MWh from stored periods: columns mwh, mean_mw, n, expected, complete.

    A period labelled 24:00 local belongs to the day before (interval-end convention)."""
    if s.empty:
        return pd.DataFrame(columns=["mwh", "mean_mw", "n", "expected", "complete"])
    local = (s.index - GSE_PERIOD).tz_convert(tz)
    day = local.normalize().date
    g = s.groupby(day)
    out = pd.DataFrame({"mwh": g.sum() * PERIOD_HOURS, "mean_mw": g.mean(), "n": g.size()})
    out["expected"] = [int(timedelta(days=1) / GSE_PERIOD) for _ in out.index]  # DST-free zone
    out["complete"] = out["n"] == out["expected"]
    return out
