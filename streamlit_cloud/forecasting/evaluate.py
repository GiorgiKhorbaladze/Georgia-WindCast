"""Fair, lead-matched scoring of archived forecasts against GSE observations (Issue #57).

* Only complete intervals (every GSE period stored) are scored; coverage is reported.
* Models are compared on common cases only: same cadence, horizon, data cutoff and interval.
* Skill = 1 - MAE_model / MAE_reference on those common cases (reference: persistence).
* A bucket with fewer than MIN_DAYS independent local days or MIN_CASES cases is labelled
  ``insufficient_evidence``; no ranking or "best model" is declared from it.
* Periods are never dropped for suspected curtailment. Only constraints listed in
  ``constraints.csv`` with a public source are reported separately, next to the full score.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from forecasting.actuals import GSE_PERIOD, actual_for, daily_energy
from forecasting.contract import CADENCES, ForecastRecord
from forecasting.models import REFERENCE

TZ = ZoneInfo("Asia/Tbilisi")
MIN_DAYS = 14
MIN_CASES = 200
BOOTSTRAP = 300


@dataclass(frozen=True)
class Constraint:
    start_utc: datetime
    end_utc: datetime
    source_url: str  # public source required; non-public information is not used
    note: str = ""


def parse_constraints(text: str | None) -> list[Constraint]:
    if not text:
        return []
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if not row.get("source_url", "").startswith("https://"):
            raise ValueError("every constraint needs a public https source")
        out.append(Constraint(datetime.fromisoformat(row["start_utc"]), datetime.fromisoformat(row["end_utc"]),
                              row["source_url"], row.get("note", "")))
    return out


def scored_frame(records: list[ForecastRecord], obs: pd.Series, constraints: list[Constraint] = ()) -> pd.DataFrame:
    rows = []
    for r in records:
        actual, n, expected = actual_for(obs, r.valid_from_utc, r.valid_to_utc)
        step = CADENCES[r.cadence]
        first = pd.Timestamp(r.data_cutoff_utc).ceil(pd.Timedelta(step)).to_pydatetime()
        k = int((r.valid_from_utc - first) / step) + 1  # interval number after the cutoff
        rows.append(dict(
            model_id=r.model_id, model_version=r.model_version, cadence=r.cadence,
            horizon_min=int(k * step.total_seconds() // 60), cutoff=r.data_cutoff_utc,
            valid_from=r.valid_from_utc, issued=r.issued_at_utc, late=r.late, pred=r.prediction_mw,
            actual=actual, n=n, expected=expected, complete=n == expected and actual is not None,
            constrained=any(c.start_utc < r.valid_to_utc and r.valid_from_utc < c.end_utc for c in constraints),
            day=pd.Timestamp(r.valid_from_utc).tz_convert(TZ).date(),
        ))
    df = pd.DataFrame(rows)
    if not df.empty:
        df["error"] = df["pred"] - df["actual"].astype(float)
    return df


def _stats(e: np.ndarray) -> dict:
    return dict(mae=float(np.abs(e).mean()), rmse=float(math.sqrt((e**2).mean())), bias=float(e.mean()))


def _bootstrap_skill(m: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float] | None:
    """90 % interval of skill by resampling whole days (errors within a day are correlated)."""
    days = m["day"].unique()
    if len(days) < 2:
        return None
    by_day = {d: g for d, g in m.groupby("day")}
    vals = []
    for _ in range(BOOTSTRAP):
        pick = pd.concat([by_day[d] for d in rng.choice(days, size=len(days), replace=True)])
        ref = np.abs(pick["error_ref"]).mean()
        if ref > 0:
            vals.append(1 - np.abs(pick["error"]).mean() / ref)
    return (float(np.quantile(vals, 0.05)), float(np.quantile(vals, 0.95))) if vals else None


def leaderboard(df: pd.DataFrame, exclude_constrained: bool = False, seed: int = 57) -> list[dict]:
    """One row per (cadence, horizon, model) on complete, common cases."""
    if df.empty:
        return []
    ok = df[df["complete"]]
    if exclude_constrained:
        ok = ok[~ok["constrained"]]
    rng = np.random.default_rng(seed)
    out = []
    for (cadence, horizon), bucket in ok.groupby(["cadence", "horizon_min"]):
        ref = bucket[bucket["model_id"] == REFERENCE][["cutoff", "valid_from", "error"]]
        for model, g in bucket.groupby("model_id"):
            row = dict(cadence=cadence, horizon_min=int(horizon), model_id=model,
                       model_version=",".join(sorted(g["model_version"].unique())),
                       cases=int(len(g)), days=int(g["day"].nunique()),
                       late_share=float(g["late"].mean()), **_stats(g["error"].to_numpy()))
            m = g.merge(ref, on=["cutoff", "valid_from"], suffixes=("", "_ref"))
            ref_mae = float(np.abs(m["error_ref"]).mean()) if len(m) else 0.0
            row["common_cases"] = int(len(m))
            row["skill"] = None if model == REFERENCE or not len(m) or ref_mae == 0 else \
                float(1 - np.abs(m["error"]).mean() / ref_mae)
            row["skill_90ci"] = None if row["skill"] is None else _bootstrap_skill(m, rng)
            row["evidence"] = "sufficient" if row["days"] >= MIN_DAYS and row["cases"] >= MIN_CASES \
                else "insufficient_evidence"
            out.append(row)
    return sorted(out, key=lambda r: (r["cadence"], r["horizon_min"], r["mae"]))


def coverage(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"forecasts": 0}
    due = df[df["valid_from"] + pd.to_timedelta(df["expected"] * 3, unit="min") <= df["issued"].max()]
    return dict(forecasts=int(len(df)), matured=int(len(due)), complete=int(df["complete"].sum()),
                incomplete_or_missing=int((~df["complete"]).sum()), late_share=float(df["late"].mean()))


def daily_history(df: pd.DataFrame) -> pd.DataFrame:
    """Accuracy per local day x model x cadence x horizon (complete cases)."""
    ok = df[df["complete"]] if not df.empty else df
    if ok.empty:
        return pd.DataFrame(columns=["day", "cadence", "horizon_min", "model_id", "cases", "mae", "rmse", "bias"])
    g = ok.groupby(["day", "cadence", "horizon_min", "model_id"])["error"]
    out = pd.DataFrame({"cases": g.size(), "mae": g.apply(lambda e: e.abs().mean()),
                        "rmse": g.apply(lambda e: math.sqrt((e**2).mean())), "bias": g.mean()}).reset_index()
    return out


def day_ahead_energy(records: list[ForecastRecord], obs: pd.Series) -> pd.DataFrame:
    """Daily MWh from hourly forecasts issued before the local day starts and covering all 24 h."""
    rows = []
    actual = daily_energy(obs)
    hourly = [r for r in records if r.cadence == "1h"]
    by_issue: dict[tuple, list[ForecastRecord]] = {}
    for r in hourly:
        by_issue.setdefault((r.model_id, r.model_version, r.issued_at_utc), []).append(r)
    for (model, version, issued), recs in by_issue.items():
        days: dict = {}
        for r in recs:
            days.setdefault(pd.Timestamp(r.valid_from_utc).tz_convert(TZ).date(), []).append(r)
        for day, rs in days.items():
            start = pd.Timestamp(day).tz_localize(TZ)
            if len(rs) != 24 or issued > start:
                continue
            mwh = sum(r.prediction_mw for r in rs)  # 1 h intervals: MW x 1 h
            act = actual.loc[day] if day in actual.index else None
            rows.append(dict(model_id=model, model_version=version, issued=issued, day=day, forecast_mwh=mwh,
                             actual_mwh=None if act is None else float(act["mwh"]),
                             complete=bool(act is not None and act["complete"])))
    return pd.DataFrame(rows)


def lead_buckets() -> dict[str, tuple[timedelta, timedelta]]:
    return {"0-1h": (timedelta(0), timedelta(hours=1)), "1-6h": (timedelta(hours=1), timedelta(hours=6)),
            "6-24h": (timedelta(hours=6), timedelta(hours=24)), "24-72h": (timedelta(hours=24), timedelta(hours=72))}


__all__ = ["GSE_PERIOD", "leaderboard", "scored_frame", "coverage", "daily_history", "day_ahead_energy"]
