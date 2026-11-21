"""Monthly wind-farm generation history (Issue #52): schema, station aliases, revision ledger.

Archive layout (``history/`` on the ``data`` branch, seeded from ``history_seed/`` on main):

* ``wind_monthly.csv``: the current view, one row per (station_id, year, month).
* ``wind_monthly_revisions.csv``: append-only ledger of every change, never rewritten.
* ``sources.json``: registry of official GSE documents (hash, ETag, Last-Modified, state).
* ``monitor_state.json``: persisted timestamps of the 20-day GSE check.

Rules: values are stored in GWh exactly as published (GSE prints "million kWh", which is GWh).
A month the source leaves blank is *not reported* and has no row; a printed 0 is a reported zero.
Nothing is interpolated, extrapolated or derived from national aggregates. A changed value is
never overwritten silently: it becomes a pending revision in the ledger and only replaces the
displayed value after explicit owner approval.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, datetime

SCHEMA_VERSION = "wind_monthly/v1"
UNIT = "GWh"

# --- verification states -------------------------------------------------------------------
OWNER = "owner_compiled_unverified"  # owner workbook, not (yet) matched to an official document
VERIFIED = "gse_document_verified"  # owner value equals the value in an official GSE document
PENDING = "gse_document_pending_approval"  # official-document value awaiting owner approval
APPROVED = "gse_document_approved"  # official-document value approved by the owner
CONFLICT = "conflict_unresolved"  # owner value differs from the official document
STATES = (OWNER, VERIFIED, PENDING, APPROVED, CONFLICT)
PUBLIC_STATES = (OWNER, VERIFIED, APPROVED, CONFLICT)  # PENDING is never shown publicly
OFFICIAL_STATES = (VERIFIED, APPROVED)


# --- station alias registry ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Station:
    id: str  # same identifiers as backend/app/sites.py
    name_ka: str
    name_en: str
    aliases: tuple[str, ...]
    color: str


STATIONS: tuple[Station, ...] = (
    Station("kartli-gori", "ქართლის ქარის ელექტროსადგური", "Kartli Wind Farm",
            ("ქართლის ქარის ელ.სადგური", "ქართლის ქარის ელექტროსადგური", "ქართლის ქარი"), "#2f9e8f"),
    Station("zemo-wind", "ზემო ქარის ელექტროსადგური", "Zemo Wind Farm",
            ("ზემო ქარის ელექტროსადგური", "ზემო ქარის ელ.სადგური", "ზემო ქარი"), "#e0a243"),
    Station("ruisi", "რუისის ქარის ელექტროსადგური", "Ruisi Wind Farm",
            ("რუისის ქარის ელექტროსადგური", "რუისის ქარის ელ.სადგური", "რუისის ქარი"), "#5b7fd6"),
)
STATION_BY_ID = {s.id: s for s in STATIONS}
# Row labels that are wind *totals*, used only as a cross-check, never stored as a station.
TOTAL_ALIASES = ("სულ ქარის სადგურები", "სულ ქარის ელექტროსადგურები")


def _norm(label: str) -> str:
    text = unicodedata.normalize("NFC", label).replace("„", "").replace("“", "").replace('"', "")
    return re.sub(r"\s+", " ", text).strip()


_ALIAS = {_norm(a): s.id for s in STATIONS for a in (s.name_ka, *s.aliases)}
_TOTALS = {_norm(a) for a in TOTAL_ALIASES}


def station_for(label: str) -> str | None:
    """Exact (normalised) alias match only: no fuzzy matching, so unknown farms surface."""
    return _ALIAS.get(_norm(label))


def is_total_label(label: str) -> bool:
    return _norm(label) in _TOTALS


def looks_like_wind_station(label: str) -> bool:
    """A row naming a wind power plant: used to flag *unknown* stations, never to import them."""
    norm = _norm(label)
    return "ქარის" in norm and ("სადგურ" in norm or "ელ." in norm) and not is_total_label(norm)


# --- records -------------------------------------------------------------------------------
COLUMNS = (
    "station_id", "name_ka", "name_en", "year", "month", "energy", "unit", "verification_status",
    "source_kind", "source_url", "source_document_id", "source_sha256", "retrieved_at",
    "published_at", "revision_id", "last_modified", "pending_energy", "pending_revision_id", "note",
    "decimals",
)
COLUMNS_V1 = COLUMNS[:-1]  # files written before the printed precision was stored
LEDGER_COLUMNS = (
    "revision_id", "recorded_at", "action", "station_id", "year", "month", "old_energy",
    "new_energy", "old_status", "new_status", "source_kind", "source_url", "source_document_id",
    "source_sha256", "reason", "decimals",
)
LEDGER_COLUMNS_V1 = LEDGER_COLUMNS[:-1]  # ledgers written before precision was stored per revision
# Largest difference ever accepted as "the same value" (rounding of 2-decimal sources). Printed
# precision can only narrow it; a coarse or unknown precision never widens it to e.g. +-0.5 GWh.
MAX_MATCH_TOL = 0.005 + 1e-9


class HistoryFormatError(ValueError):
    code = "history_format_error"


@dataclass(frozen=True, slots=True)
class MonthRecord:
    station_id: str
    year: int
    month: int
    energy: float
    verification_status: str
    source_kind: str  # "owner_workbook" | "gse_balance_pdf"
    source_url: str
    source_document_id: str
    source_sha256: str
    retrieved_at: str
    published_at: str
    revision_id: int
    last_modified: str
    pending_energy: float | None = None
    pending_revision_id: int | None = None
    note: str = ""
    decimals: int | None = None  # decimals printed by the source of ``energy`` (None: not recorded)

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.station_id, self.year, self.month)


@dataclass(frozen=True, slots=True)
class Revision:
    revision_id: int
    recorded_at: str
    action: str  # insert | verify | conflict | revise_pending | approve | reject
    station_id: str
    year: int
    month: int
    old_energy: float | None
    new_energy: float | None
    old_status: str
    new_status: str
    source_kind: str
    source_url: str
    source_document_id: str
    source_sha256: str
    reason: str
    decimals: int | None = None  # printed precision of new_energy (None: not recorded)


@dataclass(frozen=True, slots=True)
class Observation:
    """One value read from a source, before it is reconciled into the archive."""

    station_id: str
    year: int
    month: int
    energy: float
    decimals: int  # printed precision, for rounding-aware comparison
    source_kind: str
    source_url: str
    source_document_id: str
    source_sha256: str
    retrieved_at: str
    published_at: str = ""
    note: str = ""


def _fmt(value: float | None) -> str:
    return "" if value is None else repr(round(value, 6))


def _opt_float(raw: str) -> float | None:
    return None if raw == "" else float(raw)


def _opt_int(raw: str) -> int | None:
    return None if raw == "" else int(raw)


def render_records(records: Iterable[MonthRecord]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for r in sorted(records, key=lambda r: (r.year, r.month, r.station_id)):
        st = STATION_BY_ID[r.station_id]
        writer.writerow([
            r.station_id, st.name_ka, st.name_en, r.year, r.month, _fmt(r.energy), UNIT,
            r.verification_status, r.source_kind, r.source_url, r.source_document_id, r.source_sha256,
            r.retrieved_at, r.published_at, r.revision_id, r.last_modified, _fmt(r.pending_energy),
            "" if r.pending_revision_id is None else r.pending_revision_id, r.note,
            "" if r.decimals is None else r.decimals,
        ])
    return out.getvalue()


def parse_records(text: str) -> list[MonthRecord]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) not in (COLUMNS, COLUMNS_V1):
        raise HistoryFormatError(f"unexpected columns {reader.fieldnames!r}")
    out: list[MonthRecord] = []
    seen: set[tuple[str, int, int]] = set()
    for row in reader:
        try:
            rec = MonthRecord(
                station_id=row["station_id"], year=int(row["year"]), month=int(row["month"]),
                energy=float(row["energy"]), verification_status=row["verification_status"],
                source_kind=row["source_kind"], source_url=row["source_url"],
                source_document_id=row["source_document_id"], source_sha256=row["source_sha256"],
                retrieved_at=row["retrieved_at"], published_at=row["published_at"],
                revision_id=int(row["revision_id"]), last_modified=row["last_modified"],
                pending_energy=_opt_float(row["pending_energy"]),
                pending_revision_id=_opt_int(row["pending_revision_id"]), note=row["note"],
                decimals=_opt_int(row.get("decimals") or ""),
            )
        except (KeyError, ValueError) as exc:
            raise HistoryFormatError(f"bad row {row!r}: {exc}") from exc
        problems = validate_record(rec)
        if row["unit"] != UNIT:
            problems.append(f"unit {row['unit']!r}")
        if rec.key in seen:
            problems.append("duplicate (station, month)")
        if problems:
            raise HistoryFormatError(f"{rec.key}: {', '.join(problems)}")
        seen.add(rec.key)
        out.append(rec)
    return out


def render_ledger(revisions: Iterable[Revision]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(LEDGER_COLUMNS)
    for rev in revisions:
        row = asdict(rev)
        row["old_energy"], row["new_energy"] = _fmt(rev.old_energy), _fmt(rev.new_energy)
        row["decimals"] = "" if rev.decimals is None else rev.decimals
        writer.writerow([row[c] for c in LEDGER_COLUMNS])
    return out.getvalue()


def parse_ledger(text: str) -> list[Revision]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) not in (LEDGER_COLUMNS, LEDGER_COLUMNS_V1):
        raise HistoryFormatError(f"unexpected ledger columns {reader.fieldnames!r}")
    out = []
    for row in reader:
        out.append(Revision(**{
            **row, "revision_id": int(row["revision_id"]), "year": int(row["year"]),
            "month": int(row["month"]), "old_energy": _opt_float(row["old_energy"]),
            "new_energy": _opt_float(row["new_energy"]), "decimals": _opt_int(row.get("decimals") or ""),
        }))
    ids = [r.revision_id for r in out]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise HistoryFormatError("ledger revision ids must be unique and increasing")
    return out


# --- validation ----------------------------------------------------------------------------
MAX_MONTHLY_GWH = 400.0  # far above any Georgian wind farm; catches unit errors (kWh, MWh)


def validate_record(rec: MonthRecord) -> list[str]:
    problems = []
    if rec.station_id not in STATION_BY_ID:
        problems.append(f"unknown station {rec.station_id!r}")
    if not 1 <= rec.month <= 12:
        problems.append(f"month {rec.month}")
    if not 1990 <= rec.year <= 2100:
        problems.append(f"year {rec.year}")
    if rec.energy != rec.energy or not 0 <= rec.energy <= MAX_MONTHLY_GWH:  # NaN or out of range
        problems.append(f"energy {rec.energy!r} outside 0-{MAX_MONTHLY_GWH} GWh")
    if rec.verification_status not in STATES:
        problems.append(f"status {rec.verification_status!r}")
    if not rec.source_sha256:
        problems.append("missing source sha256")
    return problems


def tolerance(*decimals: int) -> float:
    """Half a unit of the coarsest printed precision (plus float slack)."""
    return 0.5 * 10 ** -min(decimals) + 1e-9


# --- reconciliation ------------------------------------------------------------------------
@dataclass
class Archive:
    records: dict[tuple[str, int, int], MonthRecord]
    ledger: list[Revision]
    seed_decimals: dict = field(default_factory=dict)  # printed precision of reviewed seed cells

    @classmethod
    def empty(cls) -> Archive:
        return cls({}, [])

    @classmethod
    def load(cls, records_csv: str | None, ledger_csv: str | None) -> Archive:
        recs = parse_records(records_csv) if records_csv else []
        ledger = parse_ledger(ledger_csv) if ledger_csv else []
        return cls({r.key: r for r in recs}, ledger)

    def dump(self) -> tuple[str, str]:
        return render_records(self.records.values()), render_ledger(self.ledger)

    def _next_id(self) -> int:
        return (self.ledger[-1].revision_id + 1) if self.ledger else 1

    def _log(self, now: str, action: str, obs: Observation | MonthRecord, old: MonthRecord | None,
             new_energy: float | None, new_status: str, reason: str, decimals: int | None = None) -> int:
        rid = self._next_id()
        self.ledger.append(Revision(
            rid, now, action, obs.station_id, obs.year, obs.month,
            None if old is None else old.energy, new_energy,
            "" if old is None else old.verification_status, new_status, obs.source_kind,
            obs.source_url, obs.source_document_id, obs.source_sha256, reason,
            obs.decimals if decimals is None else decimals,
        ))
        return rid

    def _origin_decimals(self, rec: MonthRecord) -> int | None:
        """Printed precision of the value's ORIGINAL source, when it is provable: the value was
        inserted from the owner workbook and the reviewed seed records that cell's precision."""
        first = next((r for r in self.ledger if (r.station_id, r.year, r.month) == rec.key), None)
        if first is None or first.action != "insert" or first.source_kind != "owner_workbook":
            return None
        if first.new_energy is None or abs(first.new_energy - rec.energy) > 1e-9:
            return None
        return self.seed_decimals.get(rec.key)

    def apply(self, obs: Observation, now: datetime, *, initial_status: str) -> str:
        """Reconcile one observation. Returns what happened (``unchanged`` means idempotent)."""
        stamp = now.astimezone(UTC).isoformat(timespec="seconds")
        old = self.records.get((obs.station_id, obs.year, obs.month))
        src = dict(source_kind=obs.source_kind, source_url=obs.source_url,
                   source_document_id=obs.source_document_id, source_sha256=obs.source_sha256,
                   retrieved_at=obs.retrieved_at, published_at=obs.published_at)
        if old is None:
            rid = self._log(stamp, "insert", obs, None, obs.energy, initial_status, obs.note or "new record")
            self.records[(obs.station_id, obs.year, obs.month)] = MonthRecord(
                obs.station_id, obs.year, obs.month, obs.energy, initial_status, revision_id=rid,
                last_modified=stamp, note=obs.note, decimals=obs.decimals, **src)
            return "inserted"
        # Rounding tolerance from the PRINTED precision of both values, capped at MAX_MATCH_TOL. The
        # stored float cannot tell "6.00" from "6"; unknown precision never widens the tolerance.
        tol = min(tolerance(obs.decimals, old.decimals) if old.decimals is not None else tolerance(obs.decimals),
                  MAX_MATCH_TOL)
        same_value = abs(old.energy - obs.energy) <= tol
        if obs.source_sha256 == old.source_sha256 and old.decimals is None and old.source_kind == obs.source_kind:
            # Legacy record (precision not stored) re-read from the very document it cites. Its earlier
            # match is NOT taken on trust (it may come from the old +-0.5 GWh tolerance):
            # - identical values: the document's printed precision is recorded;
            # - different values: accepted only as rounding of a source whose precision is provable
            #   (owner workbook cell, from the reviewed seed) and within MAX_MATCH_TOL;
            # - otherwise the record is quarantined as a conflict with the document value pending.
            exact = abs(old.energy - obs.energy) < 1e-9
            origin = None if exact else self._origin_decimals(old)
            if exact or (origin is not None and abs(old.energy - obs.energy) <= min(tolerance(obs.decimals, origin),
                                                                                    MAX_MATCH_TOL)):
                dec = obs.decimals if exact else origin
                src_note = "document" if exact else "owner workbook (seed)"
                rid = self._log(stamp, "precision", obs, old, old.energy, old.verification_status,
                                f"printed precision recorded from the {src_note}: {dec} decimals", decimals=dec)
                del rid  # metadata only: the value's revision id stays, so reviewed approvals stay valid
                self.records[old.key] = replace(old, decimals=dec, last_modified=stamp)
                return "precision_recorded"
            rid = self._log(stamp, "conflict", obs, old, obs.energy, CONFLICT,
                            "legacy match not confirmed at printed precision; quarantined for review")
            self.records[old.key] = replace(old, verification_status=CONFLICT, pending_energy=obs.energy,
                                            pending_revision_id=rid, last_modified=stamp)
            return "legacy_conflict"
        if obs.source_sha256 == old.source_sha256 and same_value:
            return "unchanged"  # the very same document again
        if obs.source_kind == "owner_workbook":
            return "unchanged" if same_value else "owner_differs"  # re-import never overrides
        # An official document speaks about a record already in the archive.
        if same_value and old.pending_revision_id is not None:
            # The newest document agrees with the DISPLAYED value again: the earlier proposal is
            # superseded and must never be approvable afterwards (QA D).
            self._log(stamp, "withdraw", obs, old, old.energy, old.verification_status,
                      f"proposal {old.pending_revision_id} superseded: newest document matches the displayed value")
            old = replace(old, pending_energy=None, pending_revision_id=None)
            self.records[old.key] = old
        if same_value:
            if old.verification_status in (OWNER, CONFLICT):
                rid = self._log(stamp, "verify", obs, old, old.energy, VERIFIED,
                                f"matches GSE document within ±{tol:.4g} GWh")
                self.records[old.key] = replace(old, verification_status=VERIFIED, revision_id=rid,
                                                last_modified=stamp, pending_energy=None,
                                                pending_revision_id=None, **src)
                return "verified"
            if old.verification_status == PENDING:
                return "unchanged"  # same value republished; still awaits approval
            # Same value in a newer document: refresh provenance, value untouched.
            if old.source_sha256 != obs.source_sha256:
                rid = self._log(stamp, "provenance", obs, old, old.energy, old.verification_status,
                                "same value in a newer GSE document")
                self.records[old.key] = replace(old, revision_id=rid, last_modified=stamp, **src)
                return "provenance_refreshed"
            return "unchanged"
        if old.pending_energy is not None and abs(old.pending_energy - obs.energy) <= min(tolerance(obs.decimals),
                                                                                         MAX_MATCH_TOL):
            return "unchanged"  # this difference is already pending review
        if old.verification_status == PENDING:
            # Not yet public: the newest official value replaces the pending one (logged).
            rid = self._log(stamp, "revise_pending", obs, old, obs.energy, PENDING,
                            "GSE document changed a value that was still awaiting approval")
            self.records[old.key] = replace(old, energy=obs.energy, revision_id=rid,
                                            last_modified=stamp, decimals=obs.decimals, **src)
            return "pending_updated"
        action, status = ("conflict", CONFLICT) if old.verification_status in (OWNER, CONFLICT) \
            else ("revise_pending", old.verification_status)
        rid = self._log(stamp, action, obs, old, obs.energy, status,
                        "GSE document value differs from the displayed value; kept until owner review")
        self.records[old.key] = replace(old, verification_status=status, pending_energy=obs.energy,
                                        pending_revision_id=rid, last_modified=stamp)
        return "conflict" if action == "conflict" else "revision_pending"

    def approve(self, now: datetime, through_revision: int, reason: str) -> list[tuple[str, int, int]]:
        """Owner approval of every pending value up to a revision id (inclusive). Logged."""
        stamp = now.astimezone(UTC).isoformat(timespec="seconds")
        done = []
        for key, rec in sorted(self.records.items()):
            if rec.verification_status == PENDING and rec.revision_id <= through_revision:
                rid = self._log(stamp, "approve", rec, rec, rec.energy, APPROVED, reason)
                self.records[key] = replace(rec, verification_status=APPROVED, revision_id=rid,
                                            last_modified=stamp)
                done.append(key)
            elif rec.pending_revision_id is not None and rec.pending_revision_id <= through_revision:
                pending = next(r for r in self.ledger if r.revision_id == rec.pending_revision_id)
                rid = self._log(stamp, "approve", rec, rec, rec.pending_energy, APPROVED, reason, decimals=pending.decimals)
                self.records[key] = replace(
                    rec, energy=rec.pending_energy, verification_status=APPROVED, revision_id=rid,
                    last_modified=stamp, pending_energy=None, pending_revision_id=None, decimals=pending.decimals,
                    source_kind=pending.source_kind, source_url=pending.source_url,
                    source_document_id=pending.source_document_id, source_sha256=pending.source_sha256)
                done.append(key)
        return done


class ApprovalError(ValueError):
    pass


def parse_keys(text: str) -> list[tuple[str, int, int, int]]:
    """``station:YYYY-MM@revision`` items separated by commas or spaces."""
    out = []
    for item in text.replace(",", " ").split():
        try:
            station, rest = item.split(":", 1)
            period, rev = rest.split("@", 1)
            year, month = period.split("-", 1)
            out.append((station, int(year), int(month), int(rev)))
        except ValueError as exc:
            raise ApprovalError(f"bad key {item!r}; expected station:YYYY-MM@revision") from exc
    if not out:
        raise ApprovalError("no keys given")
    return out


def approve_keys(archive: Archive, now: datetime, keys: list[tuple[str, int, int, int]], reason: str) -> list:
    """Approve exactly the listed records, each at the revision the owner reviewed. All or nothing:
    if any record is missing, not pending, or has changed since that revision, nothing is approved."""
    for station, year, month, rev in keys:
        rec = archive.records.get((station, year, month))
        if rec is None:
            raise ApprovalError(f"{station} {year}-{month:02d}: not in the archive")
        current = rec.revision_id if rec.verification_status == PENDING else rec.pending_revision_id
        if current is None:
            raise ApprovalError(f"{station} {year}-{month:02d}: nothing pending")
        if current != rev:
            raise ApprovalError(f"{station} {year}-{month:02d}: pending revision is {current}, not {rev} "
                                "(the value changed after review)")
    stamp = now.astimezone(UTC).isoformat(timespec="seconds")
    done = []
    for station, year, month, _rev in keys:
        rec = archive.records[(station, year, month)]
        if rec.verification_status == PENDING:
            rid = archive._log(stamp, "approve", rec, rec, rec.energy, APPROVED, reason)
            archive.records[rec.key] = replace(rec, verification_status=APPROVED, revision_id=rid, last_modified=stamp)
        else:
            pending = next(r for r in archive.ledger if r.revision_id == rec.pending_revision_id)
            rid = archive._log(stamp, "approve", rec, rec, rec.pending_energy, APPROVED, reason, decimals=pending.decimals)
            archive.records[rec.key] = replace(
                rec, energy=rec.pending_energy, verification_status=APPROVED, revision_id=rid,
                last_modified=stamp, pending_energy=None, pending_revision_id=None, decimals=pending.decimals,
                source_kind=pending.source_kind, source_url=pending.source_url,
                source_document_id=pending.source_document_id, source_sha256=pending.source_sha256)
        done.append(rec.key)
    return done


def _decimals(value: float) -> int:
    text = repr(round(value, 6))
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def public_records(records: Iterable[MonthRecord]) -> list[MonthRecord]:
    return [r for r in records if r.verification_status in PUBLIC_STATES]


def sources_json(sources: dict) -> str:
    return json.dumps(sources, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def record_fields() -> tuple[str, ...]:
    return tuple(f.name for f in fields(MonthRecord))
