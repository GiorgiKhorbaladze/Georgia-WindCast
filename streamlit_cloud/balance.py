"""Power-system balance blocks of the GSE 3-minute export (same file as the wind aggregate).

Verified on a recorded file (15.11.2026 00:09): hydro + thermal + wind + solar = total generation,
and consumption - total generation = sum of all tie-line flows (positive = into Georgia).

Import and export are shown separately, as on GSE's own website: import = sum of positive line
flows, export = sum of negative line flows (absolute). Per tie-line block the individual
"Intercha" lines are used when present, otherwise the block's "IntchSum": in the Russia block the
sum reads 0 while its lines (Java, Nakaduli) carry the flow. On 16.11.2026 22:39 this gave import
34.7 MW (Java + Nakaduli) and export 24.1 MW (Azerbaijan), matching GSE's site within rounding/time.
The closure import - export = consumption - generation is checked by the tests.

Strict like the wind parser: defusedxml, embedded period checked by the caller, every required
block exactly once, finite values within broad bounds. Quality codes are kept verbatim per block.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ingestion.gse_parser import GseSchemaError, GseValueError, parse_export_time  # noqa: E402

BLOCKS = {  # field -> block name prefix (GSE pads names with spaces)
    "hydro": "TOTAL HYDRO STATIONS",
    "thermal": "TOTAL TERMAL STATIONS",
    "wind": "TOTAL WIND PLANTS",
    "solar": "TOTAL SUN PLANTS",
    "generation": "TOTAL GENERATION",
    "consumption": "TOTAL CONSUMPTION",
}
SOURCES = ("hydro", "thermal", "wind", "solar")
MIN_MW, MAX_MW = -500.0, 10000.0
BALANCE_PARSER_VERSION = "gse-balance-03m/2"  # /2 adds gross import and export


@dataclass(frozen=True, slots=True)
class Balance:
    period_label_local: str
    hydro: float
    thermal: float
    wind: float
    solar: float
    generation: float
    consumption: float
    imports: float
    exports: float
    quality: str  # e.g. "hydro:SUB;thermal:SUB;wind:ACT;solar:SUB;generation:SUB;consumption:SUB"

    @property
    def net_interchange(self) -> float:
        """Derived: consumption - total generation (positive = net import)."""
        return self.consumption - self.generation


def parse_balance(payload: bytes):
    """Returns (label_utc, Balance). Raises GseSchemaError/GseValueError on any surprise."""
    try:
        root = SafeET.fromstring(payload)
    except DefusedXmlException as exc:
        raise GseSchemaError(f"forbidden XML construct: {type(exc).__name__}") from exc
    except SafeET.ParseError as exc:
        raise GseSchemaError(f"not well-formed XML: {exc}") from exc
    export = root.find("Export") if root.tag == "GSE" else None
    if export is None or (export.get("Period") or "").strip() != "03M":
        raise GseSchemaError("unexpected export header")
    label_local = (export.get("Time") or "").strip()
    label_utc = parse_export_time(label_local)

    values: dict[str, float] = {}
    quality: list[str] = []
    areas = list(root.iterfind("BLOCKS/BLOCK_AREA"))
    for field, prefix in BLOCKS.items():
        matches = [b for b in areas if (b.get("Name") or "").strip().startswith(prefix)]
        if len(matches) != 1:
            raise GseSchemaError(f"expected one {prefix!r} block, found {len(matches)}")
        rows = [ta for ta in matches[0].iterfind("TA")
                if (ta.get("EL") or "").strip() == "P" and (ta.get("IN") or "").strip() == "MvAvr03m"]
        if len(rows) != 1:
            raise GseSchemaError(f"expected one P/MvAvr03m row in {prefix!r}, found {len(rows)}")
        raw = (rows[0].get("VALUE") or "").strip()
        try:
            v = float(raw)
        except ValueError as exc:
            raise GseValueError(f"non-numeric {field} {raw!r}") from exc
        if not math.isfinite(v) or not MIN_MW <= v <= MAX_MW:
            raise GseValueError(f"implausible {field} {v}")
        values[field] = 0.0 if v == 0.0 else v
        quality.append(f"{field}:{(rows[0].get('QUALITY') or '').strip() or '?'}")
    imports, exports = _tie_flows(areas)
    return label_utc, Balance(period_label_local=label_local, quality=";".join(quality),
                              imports=imports, exports=exports, **values)


@dataclass(frozen=True, slots=True)
class TieReading:
    block: str
    identifier: str
    is_subtotal: bool
    mw: float
    quality: str


def inspect_interchange(payload: bytes):
    """Return a source label and tie records for offline verification of authorized XML.

    The block and identifier are source strings, not a verified line-to-country registry.
    This diagnostic does not change the public collector or archive.
    """
    label, _ = parse_balance(payload)
    root = SafeET.fromstring(payload)
    return label, tuple(_reported_ties(list(root.iterfind("BLOCKS/BLOCK_AREA"))))


def _reported_ties(areas):
    blocks = [b for b in areas if "TIE LINES" in (b.get("Name") or "")]
    if not blocks:
        raise GseSchemaError("no tie-line blocks")
    for block in blocks:
        name = (block.get("Name") or "").strip()
        for row in block.iterfind("TA"):
            kind = (row.get("B2") or "").strip()
            if ((row.get("EL") or "").strip() != "P" or (row.get("IN") or "").strip() != "MvAvr03m"
                    or kind not in ("Intercha", "IntchSum")):
                continue
            raw = (row.get("VALUE") or "").strip()
            try:
                value = float(raw)
            except ValueError as exc:
                raise GseValueError(f"non-numeric tie flow {raw!r}") from exc
            if not math.isfinite(value) or abs(value) > MAX_MW:
                raise GseValueError(f"implausible tie flow {value}")
            yield TieReading(name, (row.get("B3") or "").strip(), kind == "IntchSum",
                             value, (row.get("QUALITY") or "").strip())


def _tie_flows(areas) -> tuple[float, float]:
    """Gross import and export (MW) over all tie-line blocks; individual lines preferred."""
    blocks = [b for b in areas if "TIE LINES" in (b.get("Name") or "")]
    if not blocks:
        raise GseSchemaError("no tie-line blocks")
    flows: list[float] = []
    for b in blocks:
        rows = [ta for ta in b.iterfind("TA")
                if (ta.get("EL") or "").strip() == "P" and (ta.get("IN") or "").strip() == "MvAvr03m"]
        lines = [ta for ta in rows if (ta.get("B2") or "").strip() == "Intercha"]
        sums = [ta for ta in rows if (ta.get("B2") or "").strip() == "IntchSum"]
        for ta in (lines or sums):
            raw = (ta.get("VALUE") or "").strip()
            try:
                v = float(raw)
            except ValueError as exc:
                raise GseValueError(f"non-numeric tie flow {raw!r}") from exc
            if not math.isfinite(v) or abs(v) > MAX_MW:
                raise GseValueError(f"implausible tie flow {v}")
            flows.append(v)
    return float(sum(v for v in flows if v > 0)), float(-sum(v for v in flows if v < 0))
