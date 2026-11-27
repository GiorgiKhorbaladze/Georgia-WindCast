"""Forecast data contract (Issue #57, stage I): ledger record, cadences, validation.

Time convention (same as the GSE archive): a 3-minute GSE value labelled ``t`` describes the
period (t-3 min, t]. A forecast interval is [valid_from, valid_to) in UTC, aligned to its cadence;
its actual value is the mean of the GSE periods whose label lies in (valid_from, valid_to].

Two leads are kept for every forecast, because the collector delivers GSE data in 15-minute
batches and a 3-minute nowcast is anchored at the last observation, not at the wall clock:

* ``horizon`` = valid_to - data_cutoff: the lead time (what the model is asked to predict ahead of
  its data). Scores and the publication gate use a different key, the evaluation horizon
  ``forecasting.evaluate.horizon_min`` (ordinal of the cadence-aligned interval after the cutoff:
  1 h cadence, cutoff 07:12 -> 08:00-09:00 is "60"); the ledger schema is unchanged;
* ``effective lead`` = valid_to - issued_at (what a user could actually see in advance).
  A record whose valid_to <= issued_at is a *late* nowcast: archived and scored, but never shown
  as a forecast of the future.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta

CONTRACT_VERSION = "wind_forecast_ledger/v1"

CADENCES: dict[str, timedelta] = {
    "3m": timedelta(minutes=3),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}
# Stage I horizons (steps of the cadence after the data cutoff).
HORIZON_STEPS: dict[str, tuple[int, ...]] = {
    "3m": (1, 2, 3, 4, 5),  # 3, 6, 9, 12, 15 minutes
    "15m": (1, 2, 4, 8, 12, 24),  # 15 min ... 6 h
    "1h": (1, 2, 3, 6, 12, 24, 48),  # 1 ... 48 h
}
GSE_PERIOD = timedelta(minutes=3)


class ContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    model_id: str
    model_version: str
    feature_version: str
    cadence: str
    issued_at_utc: datetime
    data_cutoff_utc: datetime  # label of the last GSE observation the model could use
    weather_run_utc: datetime | None  # NWP run used (must be <= issued_at), None if no weather
    valid_from_utc: datetime
    valid_to_utc: datetime
    prediction_mw: float
    q10_mw: float | None = None
    q90_mw: float | None = None
    capacity_basis: str = "none"  # "none" | capacity-registry version used for CF models
    inputs_sha256: str = ""  # hash of the exact input observations/weather used

    @property
    def horizon(self) -> timedelta:
        return self.valid_to_utc - self.data_cutoff_utc

    @property
    def effective_lead(self) -> timedelta:
        return self.valid_to_utc - self.issued_at_utc

    @property
    def late(self) -> bool:
        return self.valid_to_utc <= self.issued_at_utc

    @property
    def key(self) -> tuple:
        return (self.model_id, self.model_version, self.cadence, self.data_cutoff_utc, self.valid_from_utc)


COLUMNS = tuple(f.name for f in fields(ForecastRecord)) + ("record_sha256",)


def _iso(ts: datetime | None) -> str:
    return "" if ts is None else ts.astimezone(UTC).isoformat()


def _num(x: float | None) -> str:
    return "" if x is None else repr(round(float(x), 4))


def _digest(raw: list[str]) -> str:
    """First 16 hex digits (64 bits) of SHA-256: detects accidental edits, keeps the ledger small."""
    return hashlib.sha256("|".join(raw).encode()).hexdigest()[:16]


def row_of(rec: ForecastRecord) -> list[str]:
    raw = []
    for f in fields(ForecastRecord):
        v = getattr(rec, f.name)
        raw.append(_iso(v) if isinstance(v, datetime) or f.name == "weather_run_utc" else
                   _num(v) if isinstance(v, float) or f.name in ("q10_mw", "q90_mw") else str(v))
    return raw + [_digest(raw)]


def validate(rec: ForecastRecord) -> None:
    """Refuse any record that could carry future information or is malformed."""
    step = CADENCES.get(rec.cadence)
    if step is None:
        raise ContractError(f"unknown cadence {rec.cadence!r}")
    for name in ("issued_at_utc", "data_cutoff_utc", "valid_from_utc", "valid_to_utc"):
        if getattr(rec, name).utcoffset() is None:
            raise ContractError(f"{name} must be timezone-aware")
    if rec.valid_to_utc - rec.valid_from_utc != step:
        raise ContractError("interval length differs from cadence")
    if rec.data_cutoff_utc > rec.issued_at_utc:
        raise ContractError("data cutoff after issue time (future information)")
    if rec.valid_from_utc < rec.data_cutoff_utc:
        raise ContractError("interval starts before the data cutoff (already observed)")
    if rec.weather_run_utc is not None and rec.weather_run_utc > rec.issued_at_utc:
        raise ContractError("weather run after issue time (future information)")
    for v in (rec.prediction_mw, rec.q10_mw, rec.q90_mw):
        if v is not None and not math.isfinite(v):
            raise ContractError("non-finite prediction")
    if rec.q10_mw is not None and rec.q90_mw is not None and rec.q10_mw > rec.q90_mw:
        raise ContractError("q10 above q90")


def render(records: list[ForecastRecord]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in records:
        w.writerow(row_of(r))
    return out.getvalue()


def _dt(raw: str) -> datetime | None:
    if raw == "":
        return None
    v = datetime.fromisoformat(raw)
    if v.utcoffset() is None:
        raise ContractError(f"naive timestamp {raw!r}")
    return v.astimezone(UTC)


def parse(text: str) -> list[ForecastRecord]:
    reader = csv.reader(io.StringIO(text))
    header = tuple(next(reader, ()))
    if header != COLUMNS:
        raise ContractError(f"unexpected ledger columns {header!r}")
    out = []
    names = [f.name for f in fields(ForecastRecord)]
    for row in reader:
        if _digest(row[:-1]) != row[-1]:
            raise ContractError("ledger row hash mismatch (record was altered)")
        d = dict(zip(names, row[:-1], strict=True))
        rec = ForecastRecord(
            d["model_id"], d["model_version"], d["feature_version"], d["cadence"],
            _dt(d["issued_at_utc"]), _dt(d["data_cutoff_utc"]), _dt(d["weather_run_utc"]),
            _dt(d["valid_from_utc"]), _dt(d["valid_to_utc"]), float(d["prediction_mw"]),
            None if d["q10_mw"] == "" else float(d["q10_mw"]), None if d["q90_mw"] == "" else float(d["q90_mw"]),
            d["capacity_basis"], d["inputs_sha256"])
        validate(rec)
        out.append(rec)
    return out


def as_dict(rec: ForecastRecord) -> dict:
    return asdict(rec)
