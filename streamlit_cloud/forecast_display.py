"""Website MW forecast section (Issue #57). Shown only while ``mwmodel.PUBLISH_FORECAST`` is True,
which stays False until the owner approves publication.

Source: ``evaluation/latest.csv`` on the public ``forecast-data`` branch (the newest issue of every
model). Nothing is interpolated, padded or invented:

* rows with a non-finite or physically impossible value, an empty validity interval or an issue
  time before the data cutoff are dropped and counted;
* an issue whose data cutoff is older than ``STALE_AFTER`` is not shown as a current forecast;
* an uncertainty band is drawn only if the file carries genuine q10/q90 values for the rows.

All times are shown in Georgia time (Asia/Tbilisi, UTC+4); horizons are measured from the data
cutoff, as in the evaluation (``horizon = valid_to - cutoff``).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

TZ = "Asia/Tbilisi"
STALE_AFTER = timedelta(minutes=60)
MW_MIN, MW_MAX = -1.0, 600.0  # physical bounds for Georgia's wind fleet (MW); outside = invalid row
REQUIRED = ("model_id", "cadence", "issued", "cutoff", "valid_from", "valid_to", "mw")
CADENCES = ("15m", "1h")


@dataclass
class Latest:
    rows: pd.DataFrame
    dropped: int = 0
    problems: list[str] = field(default_factory=list)


def parse(text: str | None) -> Latest:
    if not text or not text.strip():
        return Latest(pd.DataFrame(columns=[*REQUIRED, "horizon_min"]), 0, ["missing"])
    try:
        df = pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        return Latest(pd.DataFrame(columns=[*REQUIRED, "horizon_min"]), 0, ["unreadable"])
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return Latest(pd.DataFrame(columns=[*REQUIRED, "horizon_min"]), len(df), [f"columns missing: {missing}"])
    n = len(df)
    for c in ("issued", "cutoff", "valid_from", "valid_to"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    df["mw"] = pd.to_numeric(df["mw"], errors="coerce")
    for q in ("q10", "q90"):
        if q in df.columns:
            df[q] = pd.to_numeric(df[q], errors="coerce")
    ok = (df[["issued", "cutoff", "valid_from", "valid_to"]].notna().all(axis=1)
          & df["mw"].map(lambda v: isinstance(v, float) and math.isfinite(v))
          & df["mw"].between(MW_MIN, MW_MAX)
          & (df["valid_to"] > df["valid_from"]) & (df["issued"] >= df["cutoff"]))
    df = df[ok].copy()
    df["horizon_min"] = ((df["valid_to"] - df["cutoff"]).dt.total_seconds() // 60).astype(int)
    return Latest(df.sort_values(["model_id", "cadence", "valid_from"]).reset_index(drop=True), n - len(df),
                  [] if n == len(df) else [f"{n - len(df)} invalid rows dropped"])


def is_stale(df: pd.DataFrame, now: datetime) -> bool:
    return df.empty or pd.Timestamp(now) - df["cutoff"].max() > STALE_AFTER


def series(df: pd.DataFrame, model_id: str, cadence: str) -> pd.DataFrame:
    s = df[(df.model_id == model_id) & (df.cadence == cadence)]
    if s.empty:
        return s
    newest = s["issued"].max()  # one issue only: never mix issues in one curve
    return s[s.issued == newest].sort_values("valid_from")


def has_band(s: pd.DataFrame) -> bool:
    return {"q10", "q90"} <= set(s.columns) and s[["q10", "q90"]].notna().all().all() and len(s) > 0


def default_model(df: pd.DataFrame, gate: dict | None) -> str | None:
    models = sorted(set(df.model_id))
    if not models:
        return None
    passing = [x["model_id"] for x in (gate or {}).get("passing", [])]
    for m in passing:
        if m in models:
            return m
    for m in ("damped_trend", "persistence"):
        if m in models:
            return m
    return models[0]


def local(ts) -> str:
    return pd.Timestamp(ts).tz_convert(TZ).strftime("%d.%m.%Y %H:%M")


def actual_frame(records) -> pd.DataFrame:
    """Official GSE 3-minute values (period end labels) as stored by the collector."""
    rows = [(r.period_label_utc, r.value_mw) for r in records if r.value_mw is not None]
    df = pd.DataFrame(rows, columns=["t", "mw"])
    if not df.empty:
        df["t"] = pd.to_datetime(df["t"], utc=True)
    return df.sort_values("t")
