"""Website MW forecast section (Issue #57). Shown only while ``mwmodel.PUBLISH_FORECAST`` is True,
which stays False until the owner approves publication.

Source: ``evaluation/latest.csv`` on the public ``forecast-data`` branch (the newest issue of every
model). Nothing is interpolated, padded or invented:

* rows with a non-finite or physically impossible value, an empty validity interval or an issue
  time before the data cutoff are dropped and counted;
* an issue whose data cutoff is older than ``STALE_AFTER`` is not shown as a current forecast;
* an uncertainty band is drawn only if the file carries genuine q10/q90 values for the rows.

All times are shown in Georgia time (Asia/Tbilisi, UTC+4); horizons are measured from the data
cutoff in two ways: the evaluation horizon (cadence-aligned interval ordinal, the gate key, computed
by the same function as the evaluator) and the actual lead time ``valid_to - cutoff`` shown to users.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from forecasting.contract import CADENCES as CONTRACT_CADENCES
from forecasting.evaluate import horizon_min as evaluation_horizon

TZ = "Asia/Tbilisi"
STALE_AFTER = timedelta(minutes=60)
CLOCK_SKEW = timedelta(minutes=5)  # issue/cutoff later than now + skew: invalid, not shown
# Plausibility bounds (MW), not a clamp: rows outside are dropped, never truncated.
# Floor: GSE net 3-minute values (and persistence forecasts of them) are slightly negative in calm
# (station auxiliary load; -0.11 MW seen in the ledger); below -1 MW is invalid.
# Ceiling: 105 % of the nameplate figures in forecasting/capacity.py (Kartli 20.7 + Zemo 18.75 +
# Ruisi 206.25 MW, unverified figures included as an upper bound only). This is a provisional
# sanity bound, NOT an established official fleet nameplate; dropped rows are always counted and
# reported on the page, so a capacity expansion cannot suppress values silently. Raise it with new
# capacity. The floor relates to small negative NET GSE values, not to gross generation.
MW_MIN = -1.0
MW_MAX = round(1.05 * (20.7 + 18.75 + 206.25), 1)
REQUIRED = ("model_id", "cadence", "issued", "cutoff", "valid_from", "valid_to", "mw")
CADENCES = ("15m", "1h")


@dataclass
class Latest:
    rows: pd.DataFrame
    dropped: int = 0
    problems: list[str] = field(default_factory=list)


def parse(text: str | None) -> Latest:
    if not text or not text.strip():
        return Latest(pd.DataFrame(columns=[*REQUIRED, "horizon_min", "lead_min"]), 0, ["missing"])
    try:
        df = pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        return Latest(pd.DataFrame(columns=[*REQUIRED, "horizon_min", "lead_min"]), 0, ["unreadable"])
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return Latest(pd.DataFrame(columns=[*REQUIRED, "horizon_min", "lead_min"]), len(df), [f"columns missing: {missing}"])
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
    ok &= df["cadence"].isin(list(CONTRACT_CADENCES))
    df = df[ok].copy()
    # Gate key: the evaluator's cadence-aligned interval ordinal (shared function, identical keys).
    df["horizon_min"] = [evaluation_horizon(c, f.to_pydatetime(), cad)
                         for c, f, cad in zip(df["cutoff"], df["valid_from"], df["cadence"], strict=True)]
    # Truthful timing for people: lead time from the data cutoff to the end of the interval.
    df["lead_min"] = ((df["valid_to"] - df["cutoff"]).dt.total_seconds() // 60).astype(int)
    return Latest(df.sort_values(["model_id", "cadence", "valid_from"]).reset_index(drop=True), n - len(df),
                  [] if n == len(df) else [f"{n - len(df)} invalid rows dropped"])


def status(s: pd.DataFrame, now: datetime) -> str:
    """For ONE selected series: 'ok', 'empty', 'future' (issue or cutoff after now + skew) or 'stale'."""
    if s.empty:
        return "empty"
    now = pd.Timestamp(now)
    if (s["cutoff"].max() > now + CLOCK_SKEW) or (s["issued"].max() > now + CLOCK_SKEW):
        return "future"
    if now - s["cutoff"].max() > STALE_AFTER:
        return "stale"
    return "ok"


def is_stale(df: pd.DataFrame, now: datetime) -> bool:
    return status(df, now) != "ok"


def eligible(gate: dict | None) -> dict[tuple[str, str], set[int]]:
    """Publication keys from the live gate: {(model, cadence): {horizon_min}}. Persistence never;
    only cadences this view supports (CADENCES), so a passing 3m or 1d key cannot leave an empty choice."""
    out: dict[tuple[str, str], set[int]] = {}
    for x in (gate or {}).get("passing", []):
        if x["model_id"] != "persistence" and x.get("cadence") in CADENCES:
            out.setdefault((x["model_id"], x["cadence"]), set()).add(int(x["horizon_min"]))
    return out


def publishable(s: pd.DataFrame, keys: dict, model_id: str, cadence: str) -> pd.DataFrame:
    """Only rows whose (model, cadence, horizon) passed the gate; everything else is withheld."""
    allowed = keys.get((model_id, cadence), set())
    return s[s["horizon_min"].isin(allowed)] if allowed else s.iloc[0:0]


def series(df: pd.DataFrame, model_id: str, cadence: str) -> pd.DataFrame:
    s = df[(df.model_id == model_id) & (df.cadence == cadence)]
    if s.empty:
        return s
    newest = s["issued"].max()  # one issue only: never mix issues in one curve
    return s[s.issued == newest].sort_values("valid_from")


def has_band(s: pd.DataFrame) -> bool:
    return {"q10", "q90"} <= set(s.columns) and s[["q10", "q90"]].notna().all().all() and len(s) > 0


def default_model(df: pd.DataFrame, gate: dict | None) -> str | None:
    """A model that passed the gate and has rows in the file; never persistence; None if none."""
    keys = eligible(gate)
    models = sorted({m for (m, _c) in keys} & set(df.model_id))
    return models[0] if models else None


def local(ts) -> str:
    return pd.Timestamp(ts).tz_convert(TZ).strftime("%d.%m.%Y %H:%M")


def actual_frame(records) -> pd.DataFrame:
    """Official GSE 3-minute values (period end labels) as stored by the collector."""
    rows = [(r.period_label_utc, r.value_mw) for r in records if r.value_mw is not None]
    df = pd.DataFrame(rows, columns=["t", "mw"])
    if not df.empty:
        df["t"] = pd.to_datetime(df["t"], utc=True)
    return df.sort_values("t")
