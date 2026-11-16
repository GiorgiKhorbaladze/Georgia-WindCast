"""Experimental national wind generation forecast (MW). Independent estimate, not GSE data.

Method (deliberately simple and transparent, numpy only):
- Target: hourly mean of the stored GSE 3-minute national aggregate; an hour counts only with
  >= 16 of its 20 periods (hour of the interval start, UTC).
- Predictors: ICON model wind at 80 m and 120 m at the three verified sites (speed, speed^2,
  speed^3, speed capped at 30 m/s) plus local hour of day (sin/cos). Training uses archived
  forecasts (Open-Meteo historical forecast archive, or the project's own short-lead archive), so
  no measured or future information enters the predictors.
- Model: ridge regression on standardized predictors. Fixed regularization, no tuning on test data.
- Evaluation: time-ordered split, last 25 % of paired hours (at least 24 h) held out. Compared with
  climatology (training mean by hour of day) and persistence (value H hours earlier).
- Forecast: the model refit on all paired hours, applied to the current ICON run; clipped to the
  observed range (+10 %); band = 10-90 % quantiles of held-out residuals (empirical, not a
  probabilistic guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ = ZoneInfo("Asia/Tbilisi")
HEIGHTS = (80, 120)
MIN_PERIODS_PER_HOUR = 16
MIN_PAIRED_HOURS = 168  # one week of paired hours before any model is trained
RIDGE_ALPHA = 1.0
PERSISTENCE_HORIZONS = (1, 6, 24)


def hourly_target(df: pd.DataFrame) -> pd.Series:
    """Hourly mean MW (UTC hour of interval start) where >= 16 of 20 periods are stored."""
    if not len(df):
        return pd.Series(dtype=float)
    start = df.index - pd.Timedelta(minutes=3)
    g = df["value_mw"].groupby(start.floor("h"))
    agg = g.agg(["mean", "size"])
    return agg.loc[agg["size"] >= MIN_PERIODS_PER_HOUR, "mean"]


def weather_table(series, n_sites: int) -> pd.DataFrame:
    """Packet series -> hourly table, columns (site, height) speed, index valid UTC hour."""
    cols = {}
    for i, loc in enumerate(series[:n_sites]):
        for h in HEIGHTS:
            vals = {v.valid_at: v.speed_ms for v in loc.by_height.get(h, [])}
            cols[(i, h)] = pd.Series(vals, dtype=float)
    table = pd.DataFrame(cols)
    table.index = pd.to_datetime(table.index, utc=True)
    return table.sort_index()


def reference_table(ref: dict, n_sites: int) -> pd.DataFrame:
    """Short-lead archive reference (verification.analysis_reference) -> the same table format."""
    cols: dict = {(i, h): {} for i in range(n_sites) for h in HEIGHTS}
    for (i, h, valid), (speed, _d, _r) in ref.items():
        if (i, h) in cols:
            cols[(i, h)][valid] = speed
    table = pd.DataFrame({k: pd.Series(v, dtype=float) for k, v in cols.items()})
    table.index = pd.to_datetime(table.index, utc=True)
    return table.sort_index()


def features(table: pd.DataFrame) -> pd.DataFrame:
    """Hour [h, h+1): mean of model speeds at h and h+1 (hourly instantaneous values)."""
    if table.empty or not len(table.columns):
        return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    mid = (table + table.shift(-1, freq="h").reindex(table.index)) / 2
    mid = mid.fillna(table)
    out = {}
    for col in table.columns:
        v = mid[col].clip(lower=0, upper=30)
        name = f"s{col[0]}_{col[1]}"
        out[f"{name}_v"], out[f"{name}_v2"], out[f"{name}_v3"] = v, v**2 / 10, v**3 / 100
    hours = mid.index.tz_convert(TZ).hour
    out["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    return pd.DataFrame(out, index=mid.index).dropna()


@dataclass
class Ridge:
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float

    @classmethod
    def fit(cls, X: np.ndarray, y: np.ndarray, alpha: float = RIDGE_ALPHA) -> Ridge:
        mean, scale = X.mean(axis=0), X.std(axis=0)
        scale[scale == 0] = 1.0
        Z = (X - mean) / scale
        coef = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
        return cls(mean, scale, coef, float(y.mean()))

    def predict(self, X: np.ndarray) -> np.ndarray:
        return ((X - self.mean) / self.scale) @ self.coef + self.intercept


def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    e = p - y
    return dict(mae=float(np.abs(e).mean()), rmse=float(np.sqrt((e**2).mean())), bias=float(e.mean()), n=int(len(y)))


@dataclass
class ModelResult:
    status: str  # "ok" | "insufficient"
    paired_hours: int
    train_hours: int = 0
    test_hours: int = 0
    test_start: pd.Timestamp | None = None
    model: dict = field(default_factory=dict)
    climatology: dict = field(default_factory=dict)
    persistence: dict = field(default_factory=dict)  # horizon h -> metrics on the same test hours
    forecast: pd.DataFrame | None = None  # index valid hour; columns mw, low, high
    test_frame: pd.DataFrame | None = None  # index hour; columns actual, model


def run(target: pd.Series, train_weather: pd.DataFrame, live_weather: pd.DataFrame | None,
        now: pd.Timestamp, horizon_hours: int = 48) -> ModelResult:
    X_all = features(train_weather)
    if X_all.empty or target.empty:
        return ModelResult("insufficient", 0)
    joined = X_all.join(target.rename("y"), how="inner").dropna()
    joined = joined[joined.index < now.floor("h")]
    n = len(joined)
    if n < MIN_PAIRED_HOURS:
        return ModelResult("insufficient", n)

    n_test = max(24, n // 4)
    train, test = joined.iloc[:-n_test], joined.iloc[-n_test:]
    cols = [c for c in joined.columns if c != "y"]
    m = Ridge.fit(train[cols].to_numpy(), train["y"].to_numpy())
    p_test = m.predict(test[cols].to_numpy())
    y_test = test["y"].to_numpy()
    lo_clip, hi_clip = min(0.0, float(train["y"].min())), float(train["y"].max()) * 1.1
    p_test = np.clip(p_test, lo_clip, hi_clip)

    hours_train = train.index.tz_convert(TZ).hour
    clim = train["y"].groupby(hours_train).mean()
    p_clim = clim.reindex(test.index.tz_convert(TZ).hour).fillna(train["y"].mean()).to_numpy()

    persistence = {}
    for h in PERSISTENCE_HORIZONS:
        prev = target.reindex(test.index - pd.Timedelta(hours=h)).to_numpy()
        ok = ~np.isnan(prev)
        if ok.sum():
            persistence[h] = _metrics(y_test[ok], prev[ok])

    resid = y_test - p_test
    q10, q90 = np.quantile(resid, [0.1, 0.9])

    forecast = None
    if live_weather is not None and not live_weather.empty:
        final = Ridge.fit(joined[cols].to_numpy(), joined["y"].to_numpy())
        Xf = features(live_weather)
        Xf = Xf[(Xf.index >= now.floor("h")) & (Xf.index < now.floor("h") + timedelta(hours=horizon_hours))]
        if len(Xf):
            pf = np.clip(final.predict(Xf[cols].to_numpy()), lo_clip, hi_clip)
            forecast = pd.DataFrame({"mw": pf, "low": np.clip(pf + q10, lo_clip, hi_clip),
                                     "high": np.clip(pf + q90, lo_clip, hi_clip)}, index=Xf.index)

    return ModelResult(
        "ok", n, len(train), len(test), test.index[0],
        model=_metrics(y_test, p_test), climatology=_metrics(y_test, p_clim), persistence=persistence,
        forecast=forecast, test_frame=pd.DataFrame({"actual": y_test, "model": p_test}, index=test.index),
    )
