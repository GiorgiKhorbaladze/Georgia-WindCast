"""Analytics on stored GSE national wind generation (3-minute averages, MW). Pure functions.

Conventions (documented in README):
- A GSE label marks the END of its 3-minute averaging interval (docs/sources/gse.md). Energy of one
  period = MW x 0.05 h. A Tbilisi calendar day holds the labels 00:03 ... 24:00 (480 periods), so
  the 00:00 label belongs to the previous day.
- Only stored periods are summed. Missing periods are counted and reported, never filled, so a
  total over an incomplete day is a lower-information figure, not a full-day result.
- Negative values (station auxiliary consumption at calm) are kept as published.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ = ZoneInfo("Asia/Tbilisi")
PERIOD = pd.Timedelta(minutes=3)
PERIOD_HOURS = 0.05
PERIODS_PER_DAY = 480
COMPLETE_DAY = 0.99  # a day counts as complete with >= 99 % of its periods stored


def frame(rows) -> pd.DataFrame:
    """Rows (dicts with time/value_mw/quality) -> DataFrame indexed by UTC label, sorted."""
    if not rows:
        return pd.DataFrame(columns=["value_mw", "quality"], index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame([{"time": r["time"], "value_mw": r["value_mw"], "quality": r["quality"]} for r in rows])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.drop_duplicates("time").set_index("time").sort_index()


def local_day(label: pd.Timestamp) -> date:
    """Tbilisi day of a period label (end-of-interval convention: 00:00 belongs to the day before)."""
    return (label.tz_convert(TZ) - PERIOD).date()


def day_bounds(day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last label (UTC) of a Tbilisi day: 00:03 and 24:00 local."""
    start = pd.Timestamp(day.isoformat()).tz_localize(TZ) + PERIOD
    return start.tz_convert("UTC"), (start + pd.Timedelta(minutes=3 * (PERIODS_PER_DAY - 1))).tz_convert("UTC")


def grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """All 3-minute labels in [start, end] on the :00/:03 grid."""
    first = start.ceil("3min")
    if first > end:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.date_range(first, end.floor("3min"), freq="3min")


@dataclass(frozen=True)
class DayStats:
    day: date
    energy_mwh: float | None
    peak_mw: float | None
    peak_time: pd.Timestamp | None
    stored: int
    expected: int
    in_progress: bool
    non_act: int = 0  # stored periods with a quality code other than ACT (included, flagged)

    @property
    def completeness(self) -> float:
        return self.stored / self.expected if self.expected else 0.0

    @property
    def complete(self) -> bool:
        return not self.in_progress and self.completeness >= COMPLETE_DAY


def day_stats(df: pd.DataFrame, day: date, now: pd.Timestamp, latest_due: pd.Timestamp | None = None) -> DayStats:
    """Energy/peak over the stored periods of a Tbilisi day; for today only periods already due count."""
    first, last = day_bounds(day)
    due = latest_due if latest_due is not None else now
    in_progress = last > due
    end = min(last, due)
    expected = len(grid(first, end))
    sel = df.loc[(df.index >= first) & (df.index <= end)] if len(df) else df
    if not len(sel):
        return DayStats(day, None, None, None, 0, expected, in_progress)
    part = sel["value_mw"]
    return DayStats(day, float(part.sum() * PERIOD_HOURS), float(part.max()), part.idxmax(), int(part.size),
                    expected, in_progress, int((sel["quality"] != "ACT").sum()))


@dataclass(frozen=True)
class Comparison:
    today: DayStats
    yesterday: DayStats
    yesterday_same_time: DayStats  # yesterday cut at the same time of day as today's latest due label
    delta_same_time_mwh: float | None
    delta_same_time_pct: float | None


def compare_today_yesterday(df: pd.DataFrame, now: pd.Timestamp, latest_due: pd.Timestamp) -> Comparison:
    today = local_day(latest_due)
    yday = today - timedelta(days=1)
    t = day_stats(df, today, now, latest_due)
    y = day_stats(df, yday, now, latest_due)
    y_same = day_stats(df, yday, now, latest_due - timedelta(days=1))
    delta = pct = None
    if t.energy_mwh is not None and y_same.energy_mwh is not None:
        delta = t.energy_mwh - y_same.energy_mwh
        pct = delta / abs(y_same.energy_mwh) * 100 if abs(y_same.energy_mwh) > 1e-9 else None
    return Comparison(t, y, y_same, delta, pct)


def hourly_profile(df: pd.DataFrame, day: date) -> pd.DataFrame:
    """Mean MW and stored-period count per local hour (hour of the interval start) for one day."""
    first, last = day_bounds(day)
    part = df.loc[(df.index >= first) & (df.index <= last), "value_mw"]
    if part.empty:
        return pd.DataFrame(columns=["hour", "mean_mw", "periods"])
    hours = (part.index.tz_convert(TZ) - PERIOD).hour
    out = part.groupby(hours).agg(["mean", "size"]).reset_index()
    out.columns = ["hour", "mean_mw", "periods"]
    return out


# ------------------------------------------------------------------------------- history filters

@dataclass(frozen=True)
class Filters:
    start: pd.Timestamp
    end: pd.Timestamp
    hour_from: int = 0  # local hour of interval start, inclusive
    hour_to: int = 23  # inclusive
    qualities: tuple[str, ...] | None = None  # None = all codes
    complete_days_only: bool = False


def _hour_mask(index: pd.DatetimeIndex, f: Filters) -> np.ndarray:
    hours = (index.tz_convert(TZ) - PERIOD).hour
    if f.hour_from <= f.hour_to:
        return (hours >= f.hour_from) & (hours <= f.hour_to)
    return (hours >= f.hour_from) | (hours <= f.hour_to)  # window across midnight


def apply_filters(df: pd.DataFrame, f: Filters, now: pd.Timestamp) -> tuple[pd.DataFrame, pd.DatetimeIndex, int]:
    """Filtered rows, the matching expected grid, and how many grid periods are stored at all
    (before the quality filter: excluding a quality code must not turn data into "missing")."""
    g = grid(f.start, min(f.end, now))
    g = g[_hour_mask(g, f)] if len(g) else g
    part = df.loc[(df.index >= f.start) & (df.index <= f.end)]
    if len(part):
        part = part[_hour_mask(part.index, f)]
    if f.complete_days_only:
        days = daily(df, f.start, min(f.end, now), now)
        ok = set(days.loc[days["complete"], "day"])
        keep_p = np.array([local_day(t) in ok for t in part.index], dtype=bool)
        keep_g = np.array([local_day(t) in ok for t in g], dtype=bool)
        part = part[keep_p] if len(part) else part
        g = g[keep_g] if len(g) else g
    present = int(part.index.isin(g).sum()) if len(part) else 0
    if f.qualities is not None and len(part):
        part = part[part["quality"].isin(f.qualities)]
    return part, g, present


def summary(part: pd.DataFrame, expected: pd.DatetimeIndex, present: int) -> dict:
    """Statistics of the filtered values; completeness and missing refer to the expected grid."""
    v = part["value_mw"] if len(part) else pd.Series(dtype=float)
    exp = len(expected)
    stored = int(v.size)
    stats = dict(
        stored=stored,
        expected=exp,
        missing=max(exp - present, 0),
        completeness=present / exp if exp else 0.0,
        total_mwh=float(v.sum() * PERIOD_HOURS) if stored else None,
        non_act=int((part["quality"] != "ACT").sum()) if stored else 0,
    )
    for name, fn in (("min", "min"), ("max", "max"), ("mean", "mean"), ("median", "median"), ("std", "std")):
        stats[name] = float(getattr(v, fn)()) if stored > (1 if name == "std" else 0) else None
    return stats


def daily(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, now: pd.Timestamp,
          latest_due: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per Tbilisi day touching [start, end]: energy, mean, min, max, completeness."""
    if not len(df) or start > end:
        return pd.DataFrame(columns=["day", "energy_mwh", "mean_mw", "min_mw", "max_mw", "stored", "expected", "completeness", "complete", "in_progress"])
    d0, d1 = local_day(start.ceil("3min")), local_day(end.floor("3min"))
    rows = []
    for i in range((d1 - d0).days + 1):
        day = d0 + timedelta(days=i)
        s = day_stats(df, day, now, latest_due)
        first, last = day_bounds(day)
        part = df.loc[(df.index >= first) & (df.index <= last), "value_mw"]
        rows.append(dict(day=day, energy_mwh=s.energy_mwh, mean_mw=float(part.mean()) if len(part) else None,
                         min_mw=float(part.min()) if len(part) else None, max_mw=s.peak_mw,
                         stored=s.stored, expected=s.expected, completeness=s.completeness,
                         complete=s.complete, in_progress=s.in_progress))
    return pd.DataFrame(rows)


def aggregate(days: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Weekly ('W', ISO weeks starting Monday) or monthly ('M') sums of daily energy with completeness."""
    if days.empty:
        return pd.DataFrame(columns=["period", "energy_mwh", "days", "complete_days", "completeness"])
    d = days.copy()
    d["day"] = pd.to_datetime(d["day"])
    key = d["day"].dt.to_period("W-SUN" if freq == "W" else "M")
    g = d.groupby(key)
    out = pd.DataFrame({
        "energy_mwh": g["energy_mwh"].sum(min_count=1),
        "days": g.size(),
        "complete_days": g["complete"].sum(),
        "completeness": g["stored"].sum() / g["expected"].sum().where(g["expected"].sum() > 0),
    }).reset_index(names="period")
    out["period"] = out["period"].astype(str)
    return out


def weekday_pattern(days: pd.DataFrame, min_complete_days: int = 14) -> pd.DataFrame | None:
    """Mean daily energy by weekday over complete days; None when too few days to be meaningful."""
    full = days[days["complete"]] if not days.empty else days
    if len(full) < min_complete_days:
        return None
    wd = pd.to_datetime(full["day"]).dt.weekday
    return full.groupby(wd)["energy_mwh"].agg(["mean", "size"]).reset_index(names="weekday")


def gaps(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Missing 3-minute intervals between start and end as (first missing, last missing, count)."""
    g = grid(start, end)
    if not len(g):
        return []
    missing = g[~g.isin(df.index)]
    out: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    for t in missing:
        if out and t - out[-1][1] == PERIOD:
            out[-1] = (out[-1][0], t, out[-1][2] + 1)
        else:
            out.append((t, t, 1))
    return out
