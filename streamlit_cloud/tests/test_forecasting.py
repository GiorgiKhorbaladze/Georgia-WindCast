"""Issue #57 stage I: forecast contract, ledger immutability, no-leakage, baselines, scoring."""

from __future__ import annotations

import gzip
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from forecasting import actuals, capacity, evaluate, features, ledger, monthly
from forecasting.contract import ContractError, ForecastRecord, parse, render, validate
from forecasting.models import BASELINES, DampedTrend, DiurnalClimatology, Persistence, intervals_after
from forecasting.run import issue_at

T0 = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)


def obs_series(days=5, f=lambda i: 50 + 20 * np.sin(i / 40), start=T0):
    idx = pd.date_range(start, periods=days * 480, freq="3min", tz="UTC")
    return pd.Series([f(i) for i in range(len(idx))], index=idx, dtype=float)


def rec(**kw):
    base = dict(model_id="persistence", model_version="1", feature_version="gse-only/1", cadence="15m",
                issued_at_utc=T0 + timedelta(minutes=10), data_cutoff_utc=T0, weather_run_utc=None,
                valid_from_utc=T0, valid_to_utc=T0 + timedelta(minutes=15), prediction_mw=10.0)
    base.update(kw)
    return ForecastRecord(**base)


# --- contract ------------------------------------------------------------------------------
def test_contract_refuses_future_information():
    with pytest.raises(ContractError, match="cutoff after issue"):
        validate(rec(data_cutoff_utc=T0 + timedelta(hours=1), valid_from_utc=T0 + timedelta(hours=1),
                     valid_to_utc=T0 + timedelta(hours=1, minutes=15)))
    with pytest.raises(ContractError, match="weather run after issue"):
        validate(rec(weather_run_utc=T0 + timedelta(hours=1)))
    with pytest.raises(ContractError, match="already observed"):
        validate(rec(valid_from_utc=T0 - timedelta(minutes=15), valid_to_utc=T0))
    with pytest.raises(ContractError, match="cadence"):
        validate(rec(valid_to_utc=T0 + timedelta(minutes=16)))
    with pytest.raises(ContractError, match="non-finite"):
        validate(rec(prediction_mw=float("nan")))


def test_late_nowcast_is_flagged_and_two_leads_kept():
    r = rec(issued_at_utc=T0 + timedelta(minutes=20))
    assert r.late and r.horizon == timedelta(minutes=15) and r.effective_lead == timedelta(minutes=-5)


def test_csv_round_trip_detects_tampering():
    text = render([rec()])
    assert parse(text) == [rec()]
    with pytest.raises(ContractError, match="altered"):
        parse(text.replace(",10.0,", ",11.0,"))


# --- ledger --------------------------------------------------------------------------------
def test_ledger_is_append_only_and_refuses_duplicates(tmp_path):
    assert ledger.append(tmp_path, [rec()]) == 1
    path = ledger.day_path(tmp_path, rec())
    before = path.read_bytes()
    assert ledger.append(tmp_path, [rec(valid_from_utc=T0 + timedelta(minutes=15),
                                        valid_to_utc=T0 + timedelta(minutes=30))]) == 1
    assert path.read_bytes().startswith(before)  # earlier bytes untouched
    with pytest.raises(ContractError, match="immutable"):
        ledger.append(tmp_path, [rec(prediction_mw=99.0)])
    assert len(ledger.read_all(tmp_path)) == 2
    assert gzip.decompress(path.read_bytes()).decode().count("model_id,") == 1  # one header


# --- intervals and actuals -----------------------------------------------------------------
def test_intervals_align_to_cadence_after_cutoff():
    c = T0 + timedelta(minutes=21)
    assert intervals_after(c, "3m", (1, 5))[0] == (c, c + timedelta(minutes=3))
    assert intervals_after(c, "15m", (1,))[0][0] == T0 + timedelta(minutes=30)
    assert intervals_after(c, "1h", (1,))[0][0] == T0 + timedelta(hours=1)


def test_actuals_use_interval_end_labels_and_never_fill():
    s = obs_series(1, f=lambda i: float(i))
    mean, n, expected = actuals.actual_for(s, T0, T0 + timedelta(minutes=15))
    assert (n, expected) == (5, 5) and mean == pytest.approx(np.mean([1, 2, 3, 4, 5]))  # labels 03..15
    gap = s.drop(s.index[2])
    assert actuals.actual_for(gap, T0, T0 + timedelta(minutes=15))[1:] == (4, 5)
    iv = actuals.intervals(gap, "15m")
    assert not iv.loc[pd.Timestamp(T0), "complete"]  # 00:00-00:15 lost one period
    assert iv.loc[pd.Timestamp(T0 + timedelta(minutes=15)), "complete"]


def test_daily_energy_mwh_and_completeness():
    s = obs_series(3, f=lambda i: 10.0, start=T0 - timedelta(hours=4) + timedelta(minutes=3))  # local midnight
    day = actuals.daily_energy(s)
    full = day[day["complete"]]
    assert len(full) >= 1 and full["mwh"].iloc[0] == pytest.approx(240.0)  # 10 MW x 24 h
    assert not actuals.daily_energy(s.drop(s.index[100])).iloc[0]["complete"]


# --- baselines, no leakage -----------------------------------------------------------------
def test_baselines_use_only_data_up_to_cutoff():
    s = obs_series(5)
    cutoff = s.index[2000].to_pydatetime()
    future_changed = s.copy()
    future_changed[future_changed.index > cutoff] = 1e6  # poison everything after the cutoff
    a = issue_at(s, cutoff, cutoff + timedelta(minutes=5))
    b = issue_at(future_changed, cutoff, cutoff + timedelta(minutes=5))
    assert a and [r.prediction_mw for r in a] == [r.prediction_mw for r in b]
    assert all(r.data_cutoff_utc == cutoff and r.valid_from_utc >= cutoff for r in a)


def test_issue_covers_three_cadences_and_required_nowcast_horizons():
    s = obs_series(5)
    recs = issue_at(s, s.index[-1].to_pydatetime(), s.index[-1].to_pydatetime())
    nowcast = sorted({int(r.horizon.total_seconds() // 60) for r in recs if r.cadence == "3m"})
    assert nowcast == [3, 6, 9, 12, 15]
    assert {r.cadence for r in recs} == {"3m", "15m", "1h"}
    assert {r.model_id for r in recs} == {m.model_id for m in BASELINES}


def test_persistence_trend_and_climatology_behaviour():
    s = obs_series(4, f=lambda i: float(i % 480) / 10)  # repeating ramp each day
    cutoff = s.index[-1].to_pydatetime()
    p = Persistence().predict(s, cutoff, "3m", (1,))[0]
    assert p.mw == s.iloc[-1]
    t = DampedTrend().predict(s[s.index <= s.index[-50]], s.index[-50].to_pydatetime(), "3m", (1, 5))
    assert t[1].mw > t[0].mw > s.iloc[-50]  # rising, damped
    c = DiurnalClimatology().predict(s, cutoff, "1h", (1,))[0]
    assert 0 <= c.mw <= 48


# --- evaluation ----------------------------------------------------------------------------
def test_scoring_on_common_cases_and_insufficient_evidence():
    s = obs_series(3)
    recs = []
    for c in s.index[100:1300:5]:
        recs += issue_at(s, c.to_pydatetime(), c.to_pydatetime())
    df = evaluate.scored_frame(recs, s)
    board = evaluate.leaderboard(df)
    assert board and all(r["evidence"] == "insufficient_evidence" for r in board)  # 3 days only
    ref = [r for r in board if r["model_id"] == "persistence"]
    assert all(r["skill"] is None for r in ref)
    trend = [r for r in board if r["model_id"] == "damped_trend" and r["cadence"] == "3m" and r["horizon_min"] == 3]
    assert trend[0]["common_cases"] > 0 and trend[0]["skill"] is not None


def test_incomplete_intervals_are_not_scored_and_constraints_need_public_source():
    s = obs_series(2)
    c = s.index[300].to_pydatetime()
    recs = issue_at(s, c, c)
    gap = s.drop(s.index[301:306])
    df = evaluate.scored_frame(recs, gap)
    assert not df[(df.cadence == "3m") & (df.horizon_min == 3)]["complete"].any()
    with pytest.raises(ValueError, match="public"):
        evaluate.parse_constraints("start_utc,end_utc,source_url\n2026-11-10T00:00+00:00,2026-11-10T01:00+00:00,internal\n")
    cons = evaluate.parse_constraints(
        "start_utc,end_utc,source_url\n2026-11-10T15:00+00:00,2026-11-10T16:00+00:00,https://example.org/x\n")
    df2 = evaluate.scored_frame(recs, s, cons)
    assert df2["constrained"].any() and len(evaluate.leaderboard(df2)) >= len(evaluate.leaderboard(df2, True))


def test_day_ahead_energy_needs_full_day_issued_before_start():
    s = obs_series(4, f=lambda i: 10.0, start=T0 - timedelta(hours=4) + timedelta(minutes=3))
    cutoff = (T0 + timedelta(hours=20)).replace(minute=0)  # 00:00 Tbilisi next day = 20:00 UTC
    recs = [rec(cadence="1h", model_id="flat", issued_at_utc=cutoff, data_cutoff_utc=cutoff,
                valid_from_utc=cutoff + timedelta(hours=h), valid_to_utc=cutoff + timedelta(hours=h + 1),
                prediction_mw=10.0) for h in range(24)]
    out = evaluate.day_ahead_energy(recs, s)
    assert len(out) == 1 and out.iloc[0]["forecast_mwh"] == pytest.approx(240.0)


# --- capacity, features, monthly -----------------------------------------------------------
def test_capacity_factor_disabled_while_any_operating_capacity_unverified():
    assert not capacity.capacity_factor_enabled(date(2026, 11, 20))
    assert capacity.available_mw(date(2026, 11, 20)) is None


def test_asof_weather_run_never_uses_later_or_late_retrieved_runs():
    issued = T0 + timedelta(hours=7)
    runs = [features.Run(T0, T0 + timedelta(hours=4)), features.Run(T0 + timedelta(hours=6), T0 + timedelta(hours=9)),
            features.Run(T0 + timedelta(hours=8), T0 + timedelta(hours=10))]
    assert features.asof(runs, issued) == runs[0]  # 06 UTC run existed but was not yet obtained
    assert features.asof([], issued) is None


def test_air_density_units_and_west_ablation_defined():
    assert features.air_density(1013.25, 15.0) == pytest.approx(1.225, abs=0.002)
    assert features.air_density(1013.25, 15.0, 80) < features.air_density(1013.25, 15.0)
    assert set(features.ABLATIONS) == {"local_wind", "local_weather", "local_plus_west"}
    assert "west" in features.ABLATIONS["local_plus_west"]["regions"]
    plan = features.request_plan()
    assert plan["http_requests_per_day"] == 12 and plan["weighted_calls_per_day_estimate"] < 200  # far below 10k


def test_monthly_outlook_quantiles_and_partial_first_year():
    from types import SimpleNamespace as R
    recs = [R(station_id="kartli-gori", year=2016, month=11, energy=1.8)]
    recs += [R(station_id="kartli-gori", year=y, month=11, energy=v) for y, v in zip(range(2017, 2026), range(5, 14))]
    o = monthly.station_outlook(recs, "kartli-gori", 2026, 11)
    assert o.status == "ok" and o.years_used == 9 and o.q10 < o.q50 < o.q90  # 2016 excluded (partial)
    fleet = monthly.fleet_outlook(recs, ["kartli-gori", "ruisi"], 2026, 11)
    assert fleet["status"] == "insufficient_history" and fleet["fleet_q50_gwh"] is None


def test_workflow_reads_data_branch_only_and_keeps_publication_off():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    wf = (root / ".github/workflows/forecast.yml").read_text(encoding="utf-8")
    assert "workflow_run" in wf and "pull_request" not in wf
    assert "push -q origin forecast-data" in wf and "push -q origin data" not in wf
    assert "gse.com.ge" not in wf and "|| true" in wf  # weather failure never blocks forecasting
    import mwmodel
    assert mwmodel.PUBLISH_FORECAST is False
