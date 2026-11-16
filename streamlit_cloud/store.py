"""Durable GSE history as daily CSV files (the ``data`` branch), shared by collector and app.

Layout: ``gse/YYYY/MM/YYYY-MM-DD.csv`` keyed by the UTC date of the source label, plus
``status/gse_collector.json``. One row per 3-minute period. Rows are written only from payloads
that passed the production parser and label validation; nothing is interpolated or estimated.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime

COLUMNS = (
    "period_label_utc",
    "period_label_local",
    "value_mw",
    "quality",
    "retrieved_at_utc",
    "payload_sha256",
    "parser_version",
    "revision",
)


@dataclass(frozen=True, slots=True)
class Record:
    period_label_utc: datetime
    period_label_local: str
    value_mw: float
    quality: str
    retrieved_at_utc: datetime
    payload_sha256: str
    parser_version: str
    revision: int = 0


class StoreFormatError(ValueError):
    code = "store_format_error"


def day_path(day: date) -> str:
    return f"gse/{day:%Y}/{day:%m}/{day.isoformat()}.csv"


def _ts(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise StoreFormatError(f"naive timestamp {raw!r}")
    return value.astimezone(UTC)


def parse_day_csv(text: str) -> list[Record]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise StoreFormatError(f"unexpected columns {reader.fieldnames!r}")
    out = []
    for row in reader:
        try:
            out.append(
                Record(
                    period_label_utc=_ts(row["period_label_utc"]),
                    period_label_local=row["period_label_local"],
                    value_mw=float(row["value_mw"]),
                    quality=row["quality"],
                    retrieved_at_utc=_ts(row["retrieved_at_utc"]),
                    payload_sha256=row["payload_sha256"],
                    parser_version=row["parser_version"],
                    revision=int(row["revision"]),
                )
            )
        except (KeyError, ValueError) as exc:
            raise StoreFormatError(f"bad row {row!r}: {exc}") from exc
    labels = [r.period_label_utc for r in out]
    if len(labels) != len(set(labels)):
        raise StoreFormatError("duplicate period labels")
    return sorted(out, key=lambda r: r.period_label_utc)


def render_day_csv(records: list[Record]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for r in sorted(records, key=lambda r: r.period_label_utc):
        row = asdict(r)
        row["period_label_utc"] = r.period_label_utc.isoformat()
        row["retrieved_at_utc"] = r.retrieved_at_utc.isoformat()
        row["value_mw"] = repr(r.value_mw)
        writer.writerow(row)
    return buf.getvalue()


def merge(existing: list[Record], new: Record) -> tuple[list[Record], str]:
    """Idempotent upsert by label. Returns (records, "inserted" | "unchanged" | "revised")."""
    by_label = {r.period_label_utc: r for r in existing}
    old = by_label.get(new.period_label_utc)
    if old is None:
        by_label[new.period_label_utc] = new
        outcome = "inserted"
    elif old.payload_sha256 == new.payload_sha256:
        return existing, "unchanged"
    else:  # GSE republished different bytes for a period: keep the latest, count the revision
        by_label[new.period_label_utc] = Record(
            **{f.name: getattr(new, f.name) for f in fields(Record) if f.name != "revision"},
            revision=old.revision + 1,
        )
        outcome = "revised"
    return sorted(by_label.values(), key=lambda r: r.period_label_utc), outcome


# ---------------------------------------------------------------------------- system balance

BALANCE_COLUMNS = (
    "period_label_utc", "period_label_local", "hydro_mw", "thermal_mw", "wind_mw", "solar_mw",
    "generation_mw", "consumption_mw", "quality", "retrieved_at_utc", "payload_sha256", "parser_version",
)


@dataclass(frozen=True, slots=True)
class BalanceRecord:
    period_label_utc: datetime
    period_label_local: str
    hydro_mw: float
    thermal_mw: float
    wind_mw: float
    solar_mw: float
    generation_mw: float
    consumption_mw: float
    quality: str
    retrieved_at_utc: datetime
    payload_sha256: str
    parser_version: str


def balance_day_path(day: date) -> str:
    return f"balance/{day:%Y}/{day:%m}/{day.isoformat()}.csv"


def parse_balance_csv(text: str) -> list[BalanceRecord]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != BALANCE_COLUMNS:
        raise StoreFormatError(f"unexpected balance columns {reader.fieldnames!r}")
    out = []
    for row in reader:
        try:
            out.append(BalanceRecord(
                period_label_utc=_ts(row["period_label_utc"]), period_label_local=row["period_label_local"],
                **{k: float(row[k]) for k in ("hydro_mw", "thermal_mw", "wind_mw", "solar_mw", "generation_mw", "consumption_mw")},
                quality=row["quality"], retrieved_at_utc=_ts(row["retrieved_at_utc"]),
                payload_sha256=row["payload_sha256"], parser_version=row["parser_version"]))
        except (KeyError, ValueError) as exc:
            raise StoreFormatError(f"bad balance row {row!r}: {exc}") from exc
    labels = [r.period_label_utc for r in out]
    if len(labels) != len(set(labels)):
        raise StoreFormatError("duplicate balance labels")
    return sorted(out, key=lambda r: r.period_label_utc)


def render_balance_csv(records: list[BalanceRecord]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=BALANCE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for r in sorted(records, key=lambda r: r.period_label_utc):
        row = asdict(r)
        row["period_label_utc"] = r.period_label_utc.isoformat()
        row["retrieved_at_utc"] = r.retrieved_at_utc.isoformat()
        for k in ("hydro_mw", "thermal_mw", "wind_mw", "solar_mw", "generation_mw", "consumption_mw"):
            row[k] = repr(row[k])
        writer.writerow(row)
    return buf.getvalue()


def merge_balance(existing: list[BalanceRecord], new: BalanceRecord) -> tuple[list[BalanceRecord], bool]:
    """Upsert by label; returns (records, changed). Same bytes = unchanged; new bytes replace."""
    by_label = {r.period_label_utc: r for r in existing}
    old = by_label.get(new.period_label_utc)
    if old is not None and old.payload_sha256 == new.payload_sha256:
        return existing, False
    by_label[new.period_label_utc] = new
    return sorted(by_label.values(), key=lambda r: r.period_label_utc), True
