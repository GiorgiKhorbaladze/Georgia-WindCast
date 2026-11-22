"""Challenger tournament (Issue #57, stage II): every model on the same independent day folds.

Target: hourly mean GSE MW (only hours with all 20 periods stored). Issue time t is an hour
boundary; a forecast for horizon h targets the hour [t+h-1, t+h). Features use only data known at
t: GSE hours ending <= t and, when weather is used, a run with run <= t and retrieved <= t.

Rolling origin by local day: for every test day D (after MIN_TRAIN_DAYS), each model is trained
only on rows whose target hour ended before D begins, then predicts every issue of D. Scores are
computed on cases that ALL available models predicted. The unit of independence is the day: a
bucket with N forecasts but d days is reported as d independent days, and the skill interval is a
day-block bootstrap. Below MIN_DAYS the result is "insufficient_evidence" and nothing is ranked.

Optional libraries (statsmodels, xgboost, lightgbm, catboost, torch) are imported lazily; a model
whose library is missing is reported as "unavailable", never silently dropped.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from forecasting.contract import GSE_PERIOD
from forecasting.mlmodels import ModelSpec, registry

TZ = ZoneInfo("Asia/Tbilisi")
HORIZONS = (1, 3, 6, 24)
LAGS = (1, 2, 3, 6, 12, 24)
MIN_TRAIN_DAYS = 5
MIN_DAYS = 14
BOOTSTRAP = 300


def hourly(obs: pd.Series) -> pd.Series:
    """Mean MW per hour [start, start+1h) from complete hours only (20 of 20 periods)."""
    start = (obs.index - GSE_PERIOD).floor("h")
    g = obs.groupby(start).agg(["mean", "size"])
    s = g.loc[g["size"] == 20, "mean"]
    return s.asfreq("h")  # missing hours stay NaN


def design(y: pd.Series, horizon: int, weather: WeatherFn | None = None) -> pd.DataFrame:
    """One row per issue time t (index). Columns: features known at t, and target 'y'."""
    t = y.index + pd.Timedelta(hours=1)  # the issue time right after hour y.index is complete
    X = pd.DataFrame(index=t)
    for lag in LAGS:
        X[f"lag{lag}"] = y.shift(lag - 1).to_numpy()  # lag1 = the hour that ended at t
    X["mean6"] = y.rolling(6, min_periods=6).mean().to_numpy()
    X["diff1"] = (y - y.shift(1)).to_numpy()
    target_start = t + pd.Timedelta(hours=horizon - 1)
    hours = target_start.tz_convert(TZ).hour
    X["hour_sin"], X["hour_cos"] = np.sin(2 * np.pi * hours / 24), np.cos(2 * np.pi * hours / 24)
    X["y"] = y.reindex(target_start).to_numpy()
    X["target_start"] = target_start
    if weather is not None:
        W = weather(pd.DatetimeIndex(t), pd.DatetimeIndex(target_start))
        X = X.join(W, how="left")
    return X


WeatherFn = Callable[[pd.DatetimeIndex, pd.DatetimeIndex], pd.DataFrame]


def weather_features(runs: list, load: Callable, regions: tuple[str, ...]) -> WeatherFn:
    """As-of weather predictors: for issue t, the newest run with run <= t and retrieved <= t,
    read at the target hour. Derived: west-minus-east sea-level pressure, west precipitation."""
    from forecasting.features import POINTS, asof

    cache: dict = {}
    pts = [p for p in POINTS if p.region in regions]
    west = [p.id for p in POINTS if p.region == "west"]
    east = [p.id for p in POINTS if p.region == "east"]

    def wide(run):
        if run not in cache:
            long = load(run.run_utc)
            cache[run] = long.pivot_table(index="valid_utc", columns=["point", "variable"], values="value")
        return cache[run]

    def fn(issues: pd.DatetimeIndex, targets: pd.DatetimeIndex) -> pd.DataFrame:
        rows = []
        for t, v in zip(issues, targets, strict=True):
            run = asof(runs, t.to_pydatetime())
            row: dict = {}
            if run is not None:
                w = wide(run)
                if v in w.index:
                    rec = w.loc[v]
                    for p in pts:
                        for var in ("wind_speed_10m", "wind_speed_80m", "wind_speed_100m", "wind_speed_120m",
                                    "temperature_2m", "pressure_msl",
                                    "precipitation", "relative_humidity_2m"):
                            row[f"{p.id}:{var}"] = rec.get((p.id, var), np.nan)
                    if "west" in regions:
                        row["dp_west_east"] = np.nanmean([rec.get((i, "pressure_msl"), np.nan) for i in west]) - \
                            np.nanmean([rec.get((i, "pressure_msl"), np.nan) for i in east])
                        row["precip_west"] = np.nansum([rec.get((i, "precipitation"), np.nan) for i in west])
            rows.append(row)
        return pd.DataFrame(rows, index=issues)

    return fn


@dataclass
class Fold:
    day: object
    train: pd.DataFrame
    test: pd.DataFrame


def folds(X: pd.DataFrame, min_train_days: int = MIN_TRAIN_DAYS) -> list[Fold]:
    days = sorted(set(pd.DatetimeIndex(X.index).tz_convert(TZ).date))
    out = []
    for d in days[min_train_days:]:
        start = pd.Timestamp(d).tz_localize(TZ).tz_convert("UTC")
        test = X[(X.index >= start) & (X.index < start + pd.Timedelta(days=1))]
        train = X[X["target_start"] + pd.Timedelta(hours=1) <= start]  # target ended before D: no leakage
        out.append(Fold(d, train, test))
    return out


def run(obs: pd.Series, specs: list[ModelSpec] | None = None, weather: pd.DataFrame | None = None,
        horizons: tuple[int, ...] = HORIZONS, log: Callable[[str], None] = lambda m: None) -> dict:
    specs = specs if specs is not None else registry()
    y = hourly(obs)
    status = {s.model_id: s.status() for s in specs}
    available = [s for s in specs if status[s.model_id] == "available"]
    preds = []
    for h in horizons:
        X = design(y, h, weather)
        feats = [c for c in X.columns if c not in ("y", "target_start")]
        for fold in folds(X):
            train = fold.train.dropna(subset=["y", "lag1"])
            test = fold.test.dropna(subset=["y", "lag1"])
            if len(train) < 48 or test.empty:
                continue
            for spec in available:
                try:
                    p = spec.fit_predict(train, test, feats, h, y)
                except Exception as exc:  # a failing challenger is reported, the others continue
                    status[spec.model_id] = f"error: {type(exc).__name__}"
                    log(f"{spec.model_id} h={h} {fold.day}: {exc}")
                    continue
                for issue, target_start, actual, pred in zip(test.index, test["target_start"], test["y"], p, strict=True):
                    preds.append((spec.model_id, h, fold.day, issue, target_start, float(actual), float(pred)))
    df = pd.DataFrame(preds, columns=["model_id", "horizon_h", "day", "issue", "target_start", "actual", "pred"])
    return {"status": status, "predictions": df, "scores": score(df)}


def score(df: pd.DataFrame, reference: str = "persistence", seed: int = 57) -> list[dict]:
    if df.empty:
        return []
    rng = np.random.default_rng(seed)
    out = []
    for h, g in df.groupby("horizon_h"):
        models = sorted(g["model_id"].unique())
        wide = g.pivot_table(index=["issue", "day"], columns="model_id", values="pred").dropna()  # common cases
        actual = g.drop_duplicates(["issue"]).set_index("issue")["actual"]
        if wide.empty:
            continue
        a = actual.reindex(wide.index.get_level_values("issue")).to_numpy()
        days = wide.index.get_level_values("day")
        n_days = len(set(days))
        err = {m: wide[m].to_numpy() - a for m in models}
        for m in models:
            e = err[m]
            row = dict(horizon_h=int(h), model_id=m, cases=int(len(e)), independent_days=n_days,
                       mae=float(np.abs(e).mean()), rmse=float(math.sqrt((e**2).mean())), bias=float(e.mean()))
            if m != reference and reference in err:
                ref = np.abs(err[reference])
                row["skill"] = float(1 - np.abs(e).mean() / ref.mean()) if ref.mean() > 0 else None
                row["skill_90ci"] = _day_bootstrap(np.abs(e), ref, np.asarray(days), rng)
            else:
                row["skill"], row["skill_90ci"] = None, None
            row["evidence"] = "sufficient" if n_days >= MIN_DAYS else "insufficient_evidence"
            out.append(row)
    return sorted(out, key=lambda r: (r["horizon_h"], r["mae"]))


def _day_bootstrap(abs_e: np.ndarray, abs_ref: np.ndarray, days: np.ndarray, rng) -> list[float] | None:
    uniq = np.unique(days)
    if len(uniq) < 2:
        return None
    idx = {d: np.where(days == d)[0] for d in uniq}
    vals = []
    for _ in range(BOOTSTRAP):
        pick = np.concatenate([idx[d] for d in rng.choice(uniq, size=len(uniq), replace=True)])
        r = abs_ref[pick].mean()
        if r > 0:
            vals.append(1 - abs_e[pick].mean() / r)
    return [float(np.quantile(vals, 0.05)), float(np.quantile(vals, 0.95))] if vals else None
