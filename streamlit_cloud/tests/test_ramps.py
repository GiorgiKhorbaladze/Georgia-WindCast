"""National wind-generation ramps (Issue #33, feature 1): exact endpoints, no interpolation."""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import page_text

import ramps as rp
from i18n import tr

T0 = pd.Timestamp("2026-11-16T19:00:00Z")  # 23:00 Tbilisi


def series(values, start=T0, quality="ACT", skip=(), codes=None):
    """3-minute labels from start; `skip` drops label indexes (missing periods)."""
    idx, vals, qs = [], [], []
    for i, v in enumerate(values):
        if i in skip:
            continue
        idx.append(start + i * rp.PERIOD)
        vals.append(float(v))
        qs.append((codes or {}).get(i, quality))
    return pd.DataFrame({"value_mw": vals, "quality": qs}, index=pd.DatetimeIndex(idx, tz="UTC"))


def test_sign_and_size_of_a_15_minute_ramp():
    df = series([100, 110, 120, 130, 140, 150, 140])  # +10 MW per 3 min, then -10
    d = rp.deltas(df, rp.HORIZONS["15min"])
    assert list(d.index) == [T0 + 5 * rp.PERIOD, T0 + 6 * rp.PERIOD]
    assert list(d["delta_mw"]) == [50.0, 30.0]  # 150-100, 140-110
    assert list(d["mw_per_min"]) == [pytest.approx(50 / 15), pytest.approx(2.0)]


def test_decrease_is_negative():
    df = series([200, 190, 180, 170, 160, 150])
    d = rp.deltas(df, rp.HORIZONS["15min"])
    assert list(d["delta_mw"]) == [-50.0]


def test_missing_endpoint_gives_no_ramp_and_nothing_is_interpolated():
    df = series(range(0, 30), skip={5})  # label 5 missing
    d = rp.deltas(df, rp.HORIZONS["15min"])
    ends = set(d.index)
    assert T0 + 5 * rp.PERIOD not in ends  # its own window
    assert T0 + 10 * rp.PERIOD not in ends  # the window that would start at label 5
    assert T0 + 11 * rp.PERIOD in ends  # neighbours unaffected


def test_irregular_timestamps_only_exact_labels_pair():
    df = series([100, 120, 140, 160, 180, 200])
    df.index = df.index + pd.to_timedelta([0, 0, 0, 1, 0, 0], unit="min")  # one label off-grid
    d = rp.deltas(df, rp.HORIZONS["15min"])
    assert list(d["delta_mw"]) == [100.0]  # only 200-100 (labels 5 and 0) pair exactly


def test_window_crosses_tbilisi_midnight():
    start = pd.Timestamp("2026-11-16T19:48:00Z")  # 23:48 Tbilisi
    df = series(range(30), start=start)
    d = rp.deltas(df, rp.HORIZONS["1h"])
    first = d.index[0]
    assert first.tz_convert("Asia/Tbilisi").strftime("%d.%m %H:%M") == "17.11 00:48"
    assert d["start_label"].iloc[0].tz_convert("Asia/Tbilisi").strftime("%d.%m %H:%M") == "16.11 23:48"


def test_act_only_requires_act_at_both_endpoints():
    df = series([100, 100, 100, 100, 100, 150, 160], codes={0: "NRE"})
    all_ = rp.deltas(df, rp.HORIZONS["15min"])
    act = rp.deltas(df, rp.HORIZONS["15min"], act_only=True)
    assert len(all_) == 2 and len(act) == 1  # the window starting at the NRE label is excluded
    assert set(all_["q_start"]) == {"NRE", "ACT"}  # raw codes kept, not interpreted


def test_range_limits_apply_to_both_endpoints():
    df = series(range(100))
    start, end = T0 + 10 * rp.PERIOD, T0 + 40 * rp.PERIOD
    d = rp.deltas(df, rp.HORIZONS["15min"], start, end)
    assert d["start_label"].min() >= start and d.index.max() <= end
    assert len(d) == rp.possible_windows(start, end, rp.HORIZONS["15min"]) == 26


def test_stats_extremes_completeness_and_units():
    vals = [100] * 25 + [180] * 25 + [60] * 25  # +80 then -120 MW steps
    df = series(vals, skip={70})
    h = rp.HORIZONS["15min"]
    d = rp.deltas(df, h)
    s = rp.stats(d, rp.possible_windows(df.index.min(), df.index.max(), h))
    assert s.max_up == 80.0 and s.max_down == -120.0
    assert s.max_up_end == T0 + 25 * rp.PERIOD  # first window that contains the step
    assert s.max_down_end == T0 + 50 * rp.PERIOD
    assert 0 < s.completeness < 1 and s.possible == 70 and s.n == 69  # label 70 missing: only its own window drops (75 is out of range)
    assert s.p95_abs > 0 and 0 < s.share_up < 1


def test_flat_or_empty_series():
    assert rp.stats(rp.deltas(series([5] * 10), rp.HORIZONS["15min"]), 5).max_up is None
    empty = rp.deltas(series([]), rp.HORIZONS["1h"])
    assert empty.empty and rp.stats(empty, 0).n == 0
    with pytest.raises(ValueError):
        rp.deltas(series([1, 2]), pd.Timedelta(minutes=4))


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_analytics_page_shows_ramps(lang):
    import test_pages
    at = test_pages.run("analytics", lang, test_pages.durable_two_days())
    text = page_text(at)
    assert tr("ramp_note", lang) in text and tr("ramp_complete", lang) in text
    assert ("(ramp)" in tr("ramp_title", "ka"))  # Georgian term first, English in parentheses


def test_completeness_counts_only_from_the_first_stored_period():
    # page rule: possible windows start at max(range start, first stored label)
    h = rp.HORIZONS["1h"]
    df = series(range(40))
    early = df.index.min() - pd.Timedelta(days=3)
    assert rp.possible_windows(early, df.index.max(), h) > rp.possible_windows(max(early, df.index.min()), df.index.max(), h)
    d = rp.deltas(df, h, early, df.index.max())
    assert rp.stats(d, rp.possible_windows(max(early, df.index.min()), df.index.max(), h)).completeness == 1.0
