"""Comparison, aggregation, filters, statistics, accuracy and MW model (synthetic, labelled inputs).

Synthetic series below are constructed test inputs, never displayed as data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import analytics as an
import mwmodel
import numpy as np
import pandas as pd
import pytest
import verification as ver

TZ = an.TZ


def series(start_local: str, periods: int, value=10.0, quality="ACT", skip=()):
    """Constant (or callable) MW on the 3-minute grid starting at a Tbilisi label."""
    t0 = pd.Timestamp(start_local).tz_localize(TZ).tz_convert("UTC")
    rows = []
    for i in range(periods):
        if i in skip:
            continue
        t = t0 + pd.Timedelta(minutes=3 * i)
        rows.append(dict(time=t.to_pydatetime(), value_mw=value(i) if callable(value) else value, quality=quality))
    return rows


# ------------------------------------------------------------------------------ day convention

def test_day_boundary_follows_end_of_interval_labels():
    assert an.local_day(pd.Timestamp("2026-11-15 00:00", tz=TZ).tz_convert("UTC")).isoformat() == "2026-11-14"
    assert an.local_day(pd.Timestamp("2026-11-15 00:03", tz=TZ).tz_convert("UTC")).isoformat() == "2026-11-15"
    first, last = an.day_bounds(pd.Timestamp("2026-11-15").date())
    assert first.tz_convert(TZ).strftime("%d %H:%M") == "15 00:03"
    assert last.tz_convert(TZ).strftime("%d %H:%M") == "16 00:00"
    assert len(an.grid(first, last)) == 480


def test_full_day_energy_is_mw_times_hours():
    df = an.frame(series("2026-11-15 00:03", 480, 10.0))
    s = an.day_stats(df, pd.Timestamp("2026-11-15").date(), pd.Timestamp("2026-11-17", tz="UTC"))
    assert s.energy_mwh == pytest.approx(240.0)  # 10 MW for 24 h
    assert s.complete and s.completeness == 1.0 and s.peak_mw == 10.0


def test_incomplete_day_is_labelled_and_not_extrapolated():
    df = an.frame(series("2026-11-15 00:03", 480, 10.0, skip=set(range(100, 160))))
    s = an.day_stats(df, pd.Timestamp("2026-11-15").date(), pd.Timestamp("2026-11-17", tz="UTC"))
    assert not s.complete and s.stored == 420 and s.expected == 480
    assert s.energy_mwh == pytest.approx(420 * 10 * 0.05)  # only stored periods, no fill


def test_today_vs_yesterday_same_time_and_in_progress():
    rows = series("2026-11-15 00:03", 480, 10.0) + series("2026-11-16 00:03", 200, 20.0)
    df = an.frame(rows)
    due = pd.Timestamp("2026-11-16 00:03", tz=TZ).tz_convert("UTC") + pd.Timedelta(minutes=3 * 199)
    c = an.compare_today_yesterday(df, due + pd.Timedelta(minutes=2), due)
    assert c.today.in_progress and not c.today.complete and c.today.expected == 200
    assert c.today.energy_mwh == pytest.approx(200 * 20 * 0.05)
    assert c.yesterday.complete and c.yesterday.energy_mwh == pytest.approx(240.0)
    assert c.yesterday_same_time.stored == 200 and c.yesterday_same_time.energy_mwh == pytest.approx(100.0)
    assert c.delta_same_time_mwh == pytest.approx(100.0) and c.delta_same_time_pct == pytest.approx(100.0)


def test_non_act_periods_are_counted_not_dropped():
    rows = series("2026-11-15 00:03", 240, 5.0) + series("2026-11-15 12:03", 240, 5.0, quality="NRE")
    s = an.day_stats(an.frame(rows), pd.Timestamp("2026-11-15").date(), pd.Timestamp("2026-11-17", tz="UTC"))
    assert s.stored == 480 and s.non_act == 240 and s.energy_mwh == pytest.approx(120.0)


def test_hourly_profile_uses_interval_start_hour():
    prof = an.hourly_profile(an.frame(series("2026-11-15 00:03", 480, lambda i: i // 20)), pd.Timestamp("2026-11-15").date())
    assert list(prof["hour"]) == list(range(24)) and list(prof["periods"]) == [20] * 24
    assert prof.loc[prof.hour == 5, "mean_mw"].item() == 5


# ------------------------------------------------------------------------------- filters, stats

def test_quality_filter_does_not_turn_data_into_missing():
    rows = series("2026-11-15 00:03", 240, 5.0) + series("2026-11-15 12:03", 240, 7.0, quality="NRE")
    df = an.frame(rows)
    first, last = an.day_bounds(pd.Timestamp("2026-11-15").date())
    f = an.Filters(first, last, qualities=("ACT",))
    part, g, present = an.apply_filters(df, f, last + pd.Timedelta(hours=1))
    s = an.summary(part, g, present)
    assert s["stored"] == 240 and s["missing"] == 0 and s["completeness"] == 1.0
    assert s["mean"] == 5.0 and s["total_mwh"] == pytest.approx(60.0)


def test_hour_window_and_statistics():
    df = an.frame(series("2026-11-15 00:03", 480, lambda i: float(i // 20)))
    first, last = an.day_bounds(pd.Timestamp("2026-11-15").date())
    part, g, present = an.apply_filters(df, an.Filters(first, last, 10, 11), last + pd.Timedelta(hours=1))
    s = an.summary(part, g, present)
    assert s["expected"] == 40 and s["stored"] == 40
    assert (s["min"], s["max"], s["mean"], s["median"]) == (10.0, 11.0, 10.5, 10.5)
    assert s["std"] == pytest.approx(np.std([10.0] * 20 + [11.0] * 20, ddof=1))


def test_window_across_midnight():
    df = an.frame(series("2026-11-15 00:03", 480, 1.0))
    first, last = an.day_bounds(pd.Timestamp("2026-11-15").date())
    _, g, _ = an.apply_filters(df, an.Filters(first, last, 22, 1), last + pd.Timedelta(hours=1))
    assert len(g) == 4 * 20


def test_complete_days_only_and_aggregation():
    rows = series("2026-11-09 00:03", 480 * 7, 10.0, skip=set(range(480 * 2, 480 * 2 + 50)))
    df = an.frame(rows)
    start = an.day_bounds(pd.Timestamp("2026-11-09").date())[0]
    end = an.day_bounds(pd.Timestamp("2026-11-15").date())[1]
    now = end + pd.Timedelta(hours=1)
    days = an.daily(df, start, end, now)
    assert len(days) == 7 and days["complete"].sum() == 6
    part, g, present = an.apply_filters(df, an.Filters(start, end, complete_days_only=True), now)
    assert len(g) == 6 * 480 and present == 6 * 480
    weekly = an.aggregate(days, "W")
    assert weekly["energy_mwh"].sum() == pytest.approx(days["energy_mwh"].sum())
    assert an.weekday_pattern(days) is None  # fewer than 14 complete days


def test_gaps_are_grouped_intervals():
    df = an.frame(series("2026-11-15 00:03", 100, 1.0, skip={10, 11, 12, 50}))
    holes = an.gaps(df, df.index.min(), df.index.max())
    assert [h[2] for h in holes] == [3, 1]


# ---------------------------------------------------------------------------------- verification

@dataclass
class HV:
    valid_at: datetime
    speed_ms: float | None
    direction_deg: float | None


@dataclass
class Loc:
    by_height: dict


def packet(run: datetime, speed, direction=lambda v: 90.0, hours=72):
    vals = [HV(run + timedelta(hours=k), speed(run + timedelta(hours=k), k), direction(run + timedelta(hours=k))) for k in range(hours + 1)]
    return dict(run=run, series=[Loc({80: vals})])


def test_accuracy_uses_later_short_lead_reference_and_lead_buckets():
    t0 = datetime(2026, 11, 10, tzinfo=UTC)
    truth = lambda v: 8.0 + (v.hour % 6)  # noqa: E731  (synthetic "true" field)
    runs = [packet(t0 + timedelta(hours=6 * i), lambda v, k: truth(v) + 0.1 * k) for i in range(12)]
    ref = ver.analysis_reference(runs)
    p = ver.pairs(runs, ref)
    assert not p.empty and (p["run"] < p["valid"] - timedelta(hours=0)).all()
    s = ver.scores(p, by=("lead",)).set_index("lead")
    assert s.loc["12-24h", "bias"] > s.loc["≤6h", "bias"] > 0  # error grows with lead, by construction
    assert s.loc["24-48h", "mae"] == pytest.approx(s.loc["24-48h", "bias"])


def test_reference_never_comes_from_the_same_run():
    run = datetime(2026, 11, 10, tzinfo=UTC)
    single = [packet(run, lambda v, k: 5.0)]
    assert ver.pairs(single, ver.analysis_reference(single)).empty


def test_direction_error_is_circular_and_ignores_calm():
    df = pd.DataFrame([
        dict(site=0, height=80, lead="≤6h", f_speed=10, r_speed=10, f_dir=350, r_dir=10),
        dict(site=0, height=80, lead="≤6h", f_speed=1, r_speed=1, f_dir=0, r_dir=180),
    ])
    s = ver.scores(df)
    assert s.loc[0, "dir_mae"] == 20 and s.loc[0, "dir_n"] == 1


# ------------------------------------------------------------------------------------- MW model

def synthetic(hours: int, noise: float = 2.0, seed: int = 1):
    """Synthetic wind and generation with a known cubic relationship (test input only)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-10-01", periods=hours, freq="h", tz="UTC")
    wind = 6 + 4 * np.sin(np.arange(hours) / 9.0) + rng.normal(0, 0.5, hours)
    table = pd.DataFrame({(i, h): wind * (1 + 0.05 * i) for i in range(3) for h in mwmodel.HEIGHTS}, index=idx)
    gen = np.clip(0.4 * np.clip(wind, 0, None) ** 3, 0, 230) + rng.normal(0, noise, hours)
    rows = []
    for t, g in zip(idx, gen, strict=True):
        for k in range(1, 21):
            rows.append(dict(time=(t + pd.Timedelta(minutes=3 * k)).to_pydatetime(), value_mw=float(g), quality="ACT"))
    return table, an.frame(rows)


def test_model_needs_a_week_of_paired_hours():
    table, df = synthetic(100)
    res = mwmodel.run(mwmodel.hourly_target(df), table, None, pd.Timestamp("2026-12-01", tz="UTC"))
    assert res.status == "insufficient" and res.paired_hours < mwmodel.MIN_PAIRED_HOURS and res.forecast is None


def test_model_learns_relationship_without_leakage_and_reports_baselines():
    table, df = synthetic(24 * 20)
    now = table.index[-1] + pd.Timedelta(hours=1)
    future = synthetic(24 * 22)[0].iloc[24 * 20:]
    res = mwmodel.run(mwmodel.hourly_target(df), table, future, now)
    assert res.status == "ok" and res.train_hours + res.test_hours == res.paired_hours
    assert res.test_frame.index.min() > table.index[res.train_hours - 1]  # strictly after training
    assert res.model["mae"] < res.climatology["mae"]  # beats climatology on held-out hours
    assert set(res.persistence) <= {1, 6, 24}
    assert res.forecast is not None and len(res.forecast) > 0
    assert (res.forecast["low"] <= res.forecast["mw"]).all() and (res.forecast["mw"] <= res.forecast["high"]).all()
    assert res.forecast.index.min() >= now.floor("h")


def test_hourly_target_requires_most_periods():
    df = an.frame(series("2026-11-15 00:03", 40, 1.0, skip=set(range(25, 40))))  # 2nd hour: 5/20 periods
    target = mwmodel.hourly_target(df)
    assert len(target) == 1
