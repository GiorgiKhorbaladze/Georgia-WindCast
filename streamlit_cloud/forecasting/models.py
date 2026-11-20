"""Forecasting models behind one interface (Issue #57). Stage I: transparent baselines only.

Every model receives only observations labelled <= data_cutoff (the caller slices them) and,
when it uses weather, only NWP runs issued <= issued_at. Candidates that are not implemented yet
are listed in CANDIDATES with what they need; none is ranked in advance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from forecasting.contract import CADENCES, GSE_PERIOD

TZ = ZoneInfo("Asia/Tbilisi")


@dataclass(frozen=True)
class Point:
    valid_from: datetime
    valid_to: datetime
    mw: float
    q10: float | None = None
    q90: float | None = None


def intervals_after(cutoff: datetime, cadence: str, steps: tuple[int, ...]) -> list[tuple[datetime, datetime]]:
    """Cadence-aligned intervals starting at or after the cutoff (3-minute: cutoff + k*3 min)."""
    step = CADENCES[cadence]
    ts = pd.Timestamp(cutoff)
    first = ts.ceil(pd.Timedelta(step)).to_pydatetime()
    return [(first + (k - 1) * step, first + k * step) for k in steps]


def _bounds(obs: pd.Series) -> tuple[float, float]:
    recent = obs[obs.index > obs.index[-1] - pd.Timedelta(days=14)]
    return 0.0, float(recent.max()) * 1.1 if len(recent) else math.inf


class Forecaster:
    model_id = "base"
    version = "0"
    feature_version = "gse-only/1"
    cadences: tuple[str, ...] = ()
    min_history = timedelta(hours=1)

    def ready(self, obs: pd.Series) -> bool:
        return len(obs) > 1 and obs.index[-1] - obs.index[0] >= self.min_history

    def predict(self, obs: pd.Series, cutoff: datetime, cadence: str, steps: tuple[int, ...]) -> list[Point]:
        raise NotImplementedError


class Persistence(Forecaster):
    """Last observed level: the last 3-minute value, or the mean of the last full cadence window."""

    model_id, version = "persistence", "1"
    cadences = ("3m", "15m", "1h")
    min_history = timedelta(minutes=3)

    def predict(self, obs, cutoff, cadence, steps):
        window = obs[obs.index > cutoff - CADENCES[cadence]]
        level = float(window.mean()) if len(window) else float(obs.iloc[-1])
        return [Point(a, b, level) for a, b in intervals_after(cutoff, cadence, steps)]


class DampedTrend(Forecaster):
    """Least-squares slope of the last 30 minutes, damped with a 30-minute e-folding time."""

    model_id, version = "damped_trend", "1"
    cadences = ("3m", "15m", "1h")
    min_history = timedelta(minutes=30)
    WINDOW = timedelta(minutes=30)
    TAU_MIN = 30.0

    def predict(self, obs, cutoff, cadence, steps):
        w = obs[obs.index > cutoff - self.WINDOW]
        lo, hi = _bounds(obs)
        last = float(obs.iloc[-1])
        slope = 0.0
        if len(w) >= 5:
            x = (w.index - w.index[-1]).total_seconds().to_numpy() / 60
            slope = float(np.polyfit(x, w.to_numpy(), 1)[0])  # MW per minute
        out = []
        for a, b in intervals_after(cutoff, cadence, steps):
            mid = ((a - cutoff) + (b - cutoff)).total_seconds() / 120  # minutes to interval middle
            gain = self.TAU_MIN * (1 - math.exp(-mid / self.TAU_MIN))  # integral of damped slope
            out.append(Point(a, b, min(max(last + slope * gain, lo), hi)))
        return out


class DiurnalClimatology(Forecaster):
    """Mean of past values at the same local time of day (hour), from data before the cutoff."""

    model_id, version = "climatology", "1"
    cadences = ("3m", "15m", "1h")
    min_history = timedelta(days=3)
    LOOKBACK = timedelta(days=28)

    def predict(self, obs, cutoff, cadence, steps):
        past = obs[obs.index > cutoff - self.LOOKBACK]
        hours = (past.index - GSE_PERIOD).tz_convert(TZ).hour
        by_hour = past.groupby(hours).mean()
        overall = float(past.mean())
        out = []
        for a, b in intervals_after(cutoff, cadence, steps):
            h = pd.Timestamp(a).tz_convert(TZ).hour
            out.append(Point(a, b, float(by_hour.get(h, overall))))
        return out


BASELINES: tuple[Forecaster, ...] = (Persistence(), DampedTrend(), DiurnalClimatology())
# Lead-matched reference for skill scores: persistence for nowcasts; at 24 h and beyond the
# better of persistence and climatology is decided per evaluation window (see evaluate.py).
REFERENCE = "persistence"

# Challengers, deliberately not ranked. Each is enabled only when its data requirement is met.
CANDIDATES = {
    "ridge_icon": "Ridge on as-of ICON wind (streamlit_cloud/mwmodel.py); hourly; needs >= 168 paired hours of archived runs",
    "sarima": "SARIMA on the GSE series; needs several weeks of continuous history per fleet regime",
    "sarimax": "SARIMAX with as-of forecast weather as exogenous input; needs archived runs at every issue time",
    "xgboost": "Gradient boosting; chronological tuning; needs months of paired weather/generation",
    "lightgbm": "Gradient boosting; as above",
    "catboost": "Gradient boosting; as above",
    "gru": "Recurrent network; only with enough independent training seasons; CPU-only training in Actions",
}
