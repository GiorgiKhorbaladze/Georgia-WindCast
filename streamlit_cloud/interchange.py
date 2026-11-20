"""Cross-border exchange records of the GSE 3-minute export: data model for contract v1.

READ-ONLY, NOT WIRED IN: nothing here is called by the collector, the archive or the public app.
Publishing line-level data needs verified source rights and the owner's explicit go-ahead
(Issue #18, owner split of 20.11.2026). See docs/contracts/cross_border_flow_v1.md.

What the source contains (verified on 84 authentic files, 12.11-20.11.2026, and the two fixtures):
- Four blocks named "TOTAL <COUNTRY> TIE LINES" (AZERBAIJAN, ARMENIA, RUSSIA, TURKEY). The country
  is the block label published by GSE; it says how GSE groups the records, not where a line runs.
- Every block has one ``IntchSum`` row (B3 = a short country label, e.g. "Azerbaij").
- Only the RUSSIA block also has ``Intercha`` rows (B3 = "Salkhino", "Java", "Nakaduli"). The other
  blocks publish no individual lines; their lines are NOT reconstructed from the subtotal.
- In the RUSSIA block the subtotal read 0 in every sampled file while its lines carried up to
  57 MW, so a subtotal is never assumed to equal its lines.
- Sign: positive = flow into Georgia. Verified by arithmetic closure: consumption - generation
  equals the sum of the tie values (lines where present, else subtotal) to the published
  precision in most periods; remaining differences are reported, not hidden.
- Values are ``P`` / ``MvAvr03m``: 3-minute average active power in MW, labelled at the END of the
  interval like the wind aggregate. Quality codes are kept verbatim; their meaning is unpublished.

Persistence (e.g. "Java" reported 18.299999 with code BLS in all 84 sampled files) cannot be seen in
one file; ``persistence_flags`` marks values that stay identical across a series so a consumer can
avoid presenting a frozen reading as live.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from defusedxml import ElementTree as SafeET

from balance import MAX_MW, parse_balance
from app.ingestion.gse_parser import GseSchemaError, GseValueError

CONTRACT_VERSION = "cross_border_flow/v1"
PARSER_VERSION = "gse-interchange-03m/1"
BLOCK_SUFFIX = "TIE LINES"
ZERO_MW = 1e-6  # GSE writes "-0.000000"; anything this small is reported as zero flow


@dataclass(frozen=True, slots=True)
class TieRecord:
    """One published row. ``source_id`` is stable across files: block / kind / B3."""

    source_id: str
    block: str  # stripped block name, e.g. "TOTAL RUSSIA TIE LINES"
    block_country_label: str  # the country word in the block name, as published (e.g. "RUSSIA")
    kind: str  # "line" (Intercha) or "subtotal" (IntchSum)
    identifier: str  # B3 as published, e.g. "Nakaduli", "Azerbaij"
    mw: float  # signed, positive = into Georgia; -0.0 normalised to 0.0
    quality: str  # raw source code, meaning unpublished

    @property
    def direction(self) -> str:
        if abs(self.mw) <= ZERO_MW:
            return "zero"
        return "import" if self.mw > 0 else "export"


@dataclass(frozen=True, slots=True)
class BlockView:
    block: str
    block_country_label: str
    subtotal: TieRecord | None
    lines: tuple[TieRecord, ...]

    @property
    def lines_published(self) -> bool:
        return bool(self.lines)

    @property
    def flow_mw(self) -> float:
        """Block flow used for national arithmetic: individual lines when published, else subtotal
        (same rule as balance._tie_flows, so it reproduces the archived import/export)."""
        if self.lines:
            return float(sum(r.mw for r in self.lines))
        return self.subtotal.mw if self.subtotal is not None else 0.0

    @property
    def subtotal_minus_lines(self) -> float | None:
        if not self.lines or self.subtotal is None:
            return None
        return self.subtotal.mw - float(sum(r.mw for r in self.lines))


@dataclass(frozen=True, slots=True)
class InterchangeSnapshot:
    period_label_utc: datetime
    period_label_local: str
    payload_sha256: str
    blocks: tuple[BlockView, ...]
    consumption_mw: float
    generation_mw: float

    @property
    def records(self) -> tuple[TieRecord, ...]:
        out: list[TieRecord] = []
        for b in self.blocks:
            if b.subtotal is not None:
                out.append(b.subtotal)
            out.extend(b.lines)
        return tuple(out)

    @property
    def net_from_ties_mw(self) -> float:
        return float(sum(b.flow_mw for b in self.blocks))

    @property
    def net_from_balance_mw(self) -> float:
        """consumption - generation as published (positive = net import)."""
        return self.consumption_mw - self.generation_mw

    @property
    def residual_mw(self) -> float:
        """Published arithmetic difference, NOT a measured physical imbalance."""
        return self.net_from_balance_mw - self.net_from_ties_mw

    @property
    def gross_import_mw(self) -> float:
        return float(sum(max(0.0, r.mw) for b in self.blocks for r in (b.lines or ((b.subtotal,) if b.subtotal else ()))))

    @property
    def gross_export_mw(self) -> float:
        return float(-sum(min(0.0, r.mw) for b in self.blocks for r in (b.lines or ((b.subtotal,) if b.subtotal else ()))))


def _country_label(block_name: str) -> str:
    name = block_name.strip()
    if not (name.startswith("TOTAL ") and name.endswith(BLOCK_SUFFIX)):
        raise GseSchemaError(f"unexpected tie block name {name!r}")
    label = name[len("TOTAL "):-len(BLOCK_SUFFIX)].strip()
    if not label:
        raise GseSchemaError(f"tie block without country label {name!r}")
    return label


def parse_interchange(payload: bytes) -> InterchangeSnapshot:
    """Strict parse of all tie-line rows of one authentic 3-minute file.

    Raises GseSchemaError / GseValueError on anything unexpected: unknown row kind, duplicate
    source_id, missing or repeated subtotal, non-finite or implausible MW. The balance blocks are
    parsed with the existing strict balance parser (same file, same label).
    """
    label_utc, balance = parse_balance(payload)  # also validates header and period
    root = SafeET.fromstring(payload)
    blocks: list[BlockView] = []
    seen: set[str] = set()
    for area in root.iterfind("BLOCKS/BLOCK_AREA"):
        name = (area.get("Name") or "").strip()
        if BLOCK_SUFFIX not in name:
            continue
        country = _country_label(name)
        subtotal: TieRecord | None = None
        lines: list[TieRecord] = []
        for ta in area.iterfind("TA"):
            el, inn = (ta.get("EL") or "").strip(), (ta.get("IN") or "").strip()
            if el != "P" or inn != "MvAvr03m":
                raise GseSchemaError(f"unexpected tie row {el}/{inn} in {name!r}")
            kind_raw = (ta.get("B2") or "").strip()
            if kind_raw not in ("Intercha", "IntchSum"):
                raise GseSchemaError(f"unknown tie row kind {kind_raw!r} in {name!r}")
            ident = (ta.get("B3") or "").strip()
            if not ident:
                raise GseSchemaError(f"tie row without identifier in {name!r}")
            raw = (ta.get("VALUE") or "").strip()
            try:
                v = float(raw)
            except ValueError as exc:
                raise GseValueError(f"non-numeric tie flow {raw!r}") from exc
            if not math.isfinite(v) or abs(v) > MAX_MW:
                raise GseValueError(f"implausible tie flow {v}")
            kind = "line" if kind_raw == "Intercha" else "subtotal"
            sid = f"{country}/{kind}/{ident}"
            if sid in seen:
                raise GseSchemaError(f"duplicate tie record {sid}")
            seen.add(sid)
            rec = TieRecord(sid, name, country, kind, ident, 0.0 if v == 0 else v, (ta.get("QUALITY") or "").strip())
            if kind == "subtotal":
                subtotal = rec
            else:
                lines.append(rec)
        if subtotal is None:
            raise GseSchemaError(f"tie block {name!r} without subtotal")
        blocks.append(BlockView(name, country, subtotal, tuple(lines)))
    if not blocks:
        raise GseSchemaError("no tie-line blocks")
    return InterchangeSnapshot(label_utc, balance.period_label_local, hashlib.sha256(payload).hexdigest(),
                               tuple(blocks), balance.consumption, balance.generation)


def persistence_flags(series: Sequence[InterchangeSnapshot], min_periods: int = 20) -> dict[str, bool]:
    """source_id -> True when the value is bit-identical and non-zero in at least ``min_periods``
    consecutive snapshots (default 20 = one hour). Zero is excluded: an idle line legitimately
    reads 0. A flag means "do not present as a live measurement", not "the value is wrong"."""
    ordered = sorted(series, key=lambda s: s.period_label_utc)
    run: dict[str, int] = {}
    last: dict[str, float] = {}
    flagged: dict[str, bool] = {}
    for snap in ordered:
        for r in snap.records:
            if r.source_id in last and last[r.source_id] == r.mw and abs(r.mw) > ZERO_MW:
                run[r.source_id] += 1
            else:
                run[r.source_id] = 1
            last[r.source_id] = r.mw
            flagged[r.source_id] = flagged.get(r.source_id, False) or run[r.source_id] >= min_periods
    return flagged


def to_contract(snap: InterchangeSnapshot, persistent: Iterable[str] = ()) -> dict:
    """Contract v1 document (JSON-serialisable). See docs/contracts/cross_border_flow_v1.md."""
    frozen = set(persistent)

    def rec(r: TieRecord) -> dict:
        return {
            "source_id": r.source_id, "kind": r.kind, "identifier": r.identifier,
            "mw": round(r.mw, 6), "direction": r.direction,
            "availability": "persistent_value" if r.source_id in frozen else "reported",
            "source_quality": r.quality,
        }

    return {
        "contract": CONTRACT_VERSION,
        "parser": PARSER_VERSION,
        "period": {
            "label_utc": snap.period_label_utc.isoformat(),
            "label_local": snap.period_label_local,
            "interval_minutes": 3, "label_marks": "interval_end",
        },
        "provenance": {"source": "GSE 3-minute export", "payload_sha256": snap.payload_sha256},
        "sign_convention": "positive_into_georgia",
        "blocks": [{
            "block": b.block,
            "block_country_label": b.block_country_label,
            "lines_published": b.lines_published,
            "subtotal": rec(b.subtotal) if b.subtotal else None,
            "lines": [rec(r) for r in b.lines],
            "flow_mw": round(b.flow_mw, 6),
            "subtotal_minus_lines_mw": None if b.subtotal_minus_lines is None else round(b.subtotal_minus_lines, 6),
        } for b in snap.blocks],
        "national": {
            "net_from_ties_mw": round(snap.net_from_ties_mw, 6),
            "net_from_balance_mw": round(snap.net_from_balance_mw, 6),
            "residual_mw": round(snap.residual_mw, 6),
            "gross_import_mw": round(snap.gross_import_mw, 6),
            "gross_export_mw": round(snap.gross_export_mw, 6),
        },
        "geometry": None,  # no route or endpoint geometry is published by the source
        "publication": "not_authorized",  # owner + source-rights gate, Issue #18
    }
