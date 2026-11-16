"""Power-system balance blocks of the GSE 3-minute export (same file as the wind aggregate).

Verified on a recorded file (15.11.2026 00:09): hydro + thermal + wind + solar = total generation,
and consumption - total generation = sum of all tie-line flows (positive = into Georgia). The
per-country "IntchSum" rows are NOT used: in the recorded file the Russia sum reads 0 while its
individual lines carry 32.6 MW, so a per-country split would be misleading. Net interchange is
therefore derived as consumption - total generation and labelled as derived.

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
BALANCE_PARSER_VERSION = "gse-balance-03m/1"


@dataclass(frozen=True, slots=True)
class Balance:
    period_label_local: str
    hydro: float
    thermal: float
    wind: float
    solar: float
    generation: float
    consumption: float
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
    return label_utc, Balance(period_label_local=label_local, quality=";".join(quality), **values)
