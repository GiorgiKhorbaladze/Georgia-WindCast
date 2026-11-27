"""Challenger tournament (Issue #57 stage II): fold isolation, common cases, day-level evidence,
optional libraries reported, as-of weather features. Numpy-only models; offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from forecasting import mlmodels, tournament
from forecasting.features import POINTS, Run

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def obs(days=12, noise=0.0, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(T0 + timedelta(minutes=3), periods=days * 480, freq="3min", tz="UTC")
    base = 60 + 40 * np.sin(np.arange(len(idx)) * 2 * np.pi / 480)
    return pd.Series(base + noise * rng.standard_normal(len(idx)), index=idx)


def test_hourly_target_uses_complete_hours_only():
    s = obs(2)
    h = tournament.hourly(s.drop(s.index[5]))
    first = pd.Timestamp(T0)
    assert (first not in h.index or np.isnan(h[first])) and h.notna().sum() == 47  # 19/20: not a target


def test_folds_never_train_on_targets_inside_or_after_the_test_day():
    X = tournament.design(tournament.hourly(obs(10)), 24)
    for f in tournament.folds(X):
        start = f.test.index.min().tz_convert(tournament.TZ).normalize()
        assert (f.train["target_start"] + pd.Timedelta(hours=1) <= start).all()
        assert (f.test.index >= start).all()


def test_features_are_known_at_issue_time():
    y = tournament.hourly(obs(4))
    X = tournament.design(y, 3)
    t = X.index[30]
    assert X.loc[t, "lag1"] == y[t - pd.Timedelta(hours=1)]  # the hour that ended at t
    assert X.loc[t, "y"] == y[t + pd.Timedelta(hours=2)]  # target hour [t+2h, t+3h)


def test_tournament_scores_common_cases_and_reports_days_not_forecasts():
    specs = [mlmodels.Persistence(), mlmodels.RidgeLags()]
    res = tournament.run(obs(12, noise=3), specs=specs, horizons=(1, 6))
    rows = res["scores"]
    assert {r["model_id"] for r in rows} == {"persistence", "ridge"}
    for h in (1, 6):
        b = [r for r in rows if r["horizon_h"] == h]
        assert b[0]["cases"] == b[1]["cases"]  # identical cases for every model
        assert b[0]["independent_days"] in (7, 8) and b[0]["cases"] > 100  # days, not forecasts, count
        assert all(r["evidence"] == "insufficient_evidence" for r in b)  # < 14 independent days
    ridge = next(r for r in rows if r["model_id"] == "ridge" and r["horizon_h"] == 6)
    assert ridge["skill"] is not None and len(ridge["skill_90ci"]) == 2


def test_missing_library_is_reported_unavailable():
    class Fake(mlmodels.ModelSpec):
        def __init__(self):
            super().__init__("fake", "definitely_not_installed_lib")
    res = tournament.run(obs(8), specs=[mlmodels.Persistence(), Fake()], horizons=(1,))
    assert res["status"]["fake"] == "unavailable"
    assert {r["model_id"] for r in res["scores"]} == {"persistence"}


def test_failing_model_does_not_stop_the_others():
    class Broken(mlmodels.ModelSpec):
        def __init__(self):
            super().__init__("broken", None)

        def fit_predict(self, *a):
            raise RuntimeError("boom")
    res = tournament.run(obs(8), specs=[mlmodels.Persistence(), Broken()], horizons=(1,))
    assert res["status"]["broken"].startswith("error") and res["scores"]


def test_registry_lists_every_requested_challenger():
    assert [m.model_id for m in mlmodels.registry()] == [
        "persistence", "ridge", "sarima", "xgboost", "lightgbm", "catboost", "gru"]


def test_weather_features_respect_as_of_and_add_west_signals():
    retrieved = T0 + timedelta(hours=5)
    run = Run(T0, retrieved)
    valid = pd.date_range(T0, periods=72, freq="h", tz="UTC")
    rows = [(p.id, v, var, {"pressure_msl": 1015.0 if p.region == "west" else 1010.0,
                           "precipitation": 1.0}.get(var, 5.0))
            for p in POINTS for v in valid for var in ("pressure_msl", "precipitation", "wind_speed_80m")]
    long = pd.DataFrame(rows, columns=["point", "valid_utc", "variable", "value"])
    fn = tournament.weather_features([run], lambda r: long, ("east", "central", "west"))
    issues = pd.DatetimeIndex([T0 + timedelta(hours=4), T0 + timedelta(hours=6)])
    W = fn(issues, issues + pd.Timedelta(hours=2))
    assert W.iloc[0].isna().all() or W.iloc[0].dropna().empty  # run not yet retrieved at 04:00
    assert W.iloc[1]["dp_west_east"] == pytest.approx(5.0) and W.iloc[1]["precip_west"] == pytest.approx(3.0)


def test_tournament_workflow_is_daily_isolated_and_unpublished():
    from pathlib import Path
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/forecast-tournament.yml").read_text()
    assert 'cron: "17 2 * * *"' in wf and "group: forecast-data" in wf and "pull_request" not in wf
    assert "push -q origin forecast-data" in wf and "origin data\n" not in wf.split("push")[-1]
    import mwmodel
    assert mwmodel.PUBLISH_FORECAST is False


# --- QA T1 (#63 audit, 21.11.2026): failure isolation with missing weather / NaN output -------
def test_weather_without_training_coverage_is_not_used_and_ridge_stays_finite():
    def weather(issues, targets):  # only the last day has weather: no training coverage
        last = issues.max() - pd.Timedelta(hours=20)
        return pd.DataFrame({"gfs:wind": np.where(issues > last, 7.0, np.nan)}, index=issues)
    res = tournament.run(obs(10, noise=2), specs=[mlmodels.Persistence(), mlmodels.RidgeLags()],
                         weather=weather, horizons=(1,))
    assert res["weather_features"][1] == []  # dropped: < 80 % of training rows had it
    assert {r["model_id"] for r in res["scores"]} == {"persistence", "ridge"}
    assert all(np.isfinite(r["mae"]) for r in res["scores"])


def test_all_nan_challenger_is_excluded_not_fatal():
    class NaNModel(mlmodels.ModelSpec):
        def __init__(self):
            super().__init__("nanmodel", None)

        def fit_predict(self, train, test, feats, horizon, y):
            return np.full(len(test), np.nan)
    res = tournament.run(obs(8), specs=[mlmodels.Persistence(), NaNModel()], horizons=(1,))
    assert {r["model_id"] for r in res["scores"]} == {"persistence"}
    assert any(e["model_id"] == "nanmodel" for e in res["excluded"]) and res["notes"]["nanmodel"]


def test_partially_missing_predictions_keep_identical_cases():
    class Half(mlmodels.ModelSpec):
        def __init__(self):
            super().__init__("half", None)

        def fit_predict(self, train, test, feats, horizon, y):
            p = test["lag1"].to_numpy(dtype=float).copy()
            p[::4] = np.nan  # 75 % coverage: eligible, cohort shrinks for everyone
            return p
    res = tournament.run(obs(8), specs=[mlmodels.Persistence(), Half()], horizons=(1,))
    rows = {r["model_id"]: r for r in res["scores"]}
    assert rows["half"]["cases"] == rows["persistence"]["cases"]


def test_score_handles_absent_models_and_empty_input():
    df = pd.DataFrame([("persistence", 1, "d", pd.Timestamp("2026-11-10", tz="UTC"), None, 5.0, 4.0)],
                      columns=["model_id", "horizon_h", "day", "issue", "target_start", "actual", "pred"])
    rows, excluded = tournament.score(df, models=["persistence", "ridge"], with_excluded=True)
    assert [r["model_id"] for r in rows] == ["persistence"] and excluded[0]["model_id"] == "ridge"
    assert tournament.score(df.iloc[0:0], models=["ridge"], with_excluded=True) == ([], [{"model_id": "ridge", "reason": "no predictions"}])
    res = tournament.run(obs(8), specs=[], horizons=(1,))  # no model at all: honest empty report
    assert res["scores"] == [] and res["excluded"] == []


def test_insufficient_history_is_a_note_not_an_error():
    class Short(mlmodels.ModelSpec):
        def __init__(self):
            super().__init__("short", None)

        def fit_predict(self, *a):
            raise mlmodels.InsufficientData("not enough complete 48-hour windows")
    res = tournament.run(obs(8), specs=[mlmodels.Persistence(), Short()], horizons=(1,))
    assert res["status"]["short"] == "available"
    assert any("not enough complete" in n for n in res["notes"]["short"])
