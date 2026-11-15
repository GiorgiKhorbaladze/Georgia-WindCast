"""Parser for GSE real-time XML exports (3-minute period).

Source format verified on 2026-11-14 (see docs/sources/gse.md). Example::

    <GSE DTD_Version='1'>
    <Export Time='15.11.2026 00:09:00' Period='03M' Type='Real Time Data'/>
    <BLOCKS>
    <BLOCK_AREA Name='TOTAL WIND PLANTS                           '>
    <TA B1='AllGeorg' B2='WindPP' B3=' ' EL='P' IN='MvAvr03m' VALUE='73.599297' QUALITY='ACT'/>
    </BLOCK_AREA>
    ...

Only the national wind aggregate is extracted. The parser is strict: any structural surprise
raises :class:`GseSchemaError` instead of guessing, so schema drift can never be stored as data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

PARSER_VERSION = "gse-xml-03m/1"
SOURCE_TZ = ZoneInfo("Asia/Tbilisi")
EXPECTED_PERIOD = "03M"
WIND_BLOCK = "TOTAL WIND PLANTS"
WIND_ELEMENT = "P"
WIND_INPUT = "MvAvr03m"
# Plausibility bounds for the national wind aggregate. Small negative values (station
# auxiliary consumption at calm) are physically possible and are stored as reported.
MIN_PLAUSIBLE_MW = -50.0
MAX_PLAUSIBLE_MW = 2000.0


class GseParseError(ValueError):
    """Base class: the payload must not be stored."""

    code = "parse_error"


class GseSchemaError(GseParseError):
    code = "schema_drift"


class GseValueError(GseParseError):
    code = "invalid_value"


class GseLabelError(GseParseError):
    """The embedded Export Time does not fit the request (wrong period or in the future)."""

    code = "label_mismatch"


class GseFutureLabelError(GseLabelError):
    code = "future_label"


@dataclass(frozen=True, slots=True)
class WindReading:
    period_label_utc: datetime
    period_label_local: str
    value_mw: float
    quality: str


def parse_export_time(raw: str) -> datetime:
    """Parse ``DD.MM.YYYY HH:MM:SS`` in Asia/Tbilisi and return an aware UTC datetime."""
    try:
        local = datetime.strptime(raw.strip(), "%d.%m.%Y %H:%M:%S")  # noqa: DTZ007
    except ValueError as exc:
        raise GseSchemaError(f"unrecognised Export Time {raw!r}") from exc
    return local.replace(tzinfo=SOURCE_TZ).astimezone(UTC)


def _attr(el: Element, name: str) -> str:
    value = el.get(name)
    if value is None:
        raise GseSchemaError(f"<{el.tag}> lacks attribute {name}")
    return value


def parse_wind_export(payload: bytes) -> WindReading:
    try:
        root = SafeET.fromstring(payload)
    except DefusedXmlException as exc:
        raise GseSchemaError(f"forbidden XML construct: {type(exc).__name__}") from exc
    except SafeET.ParseError as exc:
        raise GseSchemaError(f"not well-formed XML: {exc}") from exc

    if root.tag != "GSE":
        raise GseSchemaError(f"unexpected root element <{root.tag}>")
    export = root.find("Export")
    if export is None:
        raise GseSchemaError("missing <Export> element")
    period = _attr(export, "Period").strip()
    if period != EXPECTED_PERIOD:
        raise GseSchemaError(f"unexpected Period {period!r}")
    label_local = _attr(export, "Time").strip()
    label_utc = parse_export_time(label_local)

    blocks = [
        b for b in root.iterfind("BLOCKS/BLOCK_AREA") if (b.get("Name") or "").strip() == WIND_BLOCK
    ]
    if len(blocks) != 1:
        raise GseSchemaError(f"expected one {WIND_BLOCK!r} block, found {len(blocks)}")
    entries = [
        ta
        for ta in blocks[0].iterfind("TA")
        if (ta.get("EL") or "").strip() == WIND_ELEMENT
        and (ta.get("IN") or "").strip() == WIND_INPUT
    ]
    # One aggregate entry is the verified format. More than one would mean the structure changed
    # (e.g. per-plant rows); summing them blindly could double count, so refuse instead.
    if len(entries) != 1:
        raise GseSchemaError(
            f"expected one {WIND_ELEMENT}/{WIND_INPUT} entry, found {len(entries)}"
        )
    ta = entries[0]

    raw_value = _attr(ta, "VALUE").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise GseValueError(f"non-numeric VALUE {raw_value!r}") from exc
    if not math.isfinite(value):
        raise GseValueError(f"non-finite VALUE {raw_value!r}")
    if not MIN_PLAUSIBLE_MW <= value <= MAX_PLAUSIBLE_MW:
        raise GseValueError(f"implausible VALUE {value} MW")
    if value == 0.0:
        value = 0.0  # normalise "-0.000000"

    quality = _attr(ta, "QUALITY").strip()
    if not quality:
        raise GseSchemaError("empty QUALITY")
    return WindReading(
        period_label_utc=label_utc,
        period_label_local=label_local,
        value_mw=value,
        quality=quality,
    )


def export_file_name(label_utc: datetime) -> str:
    """File name GSE uses for the period labelled ``label_utc`` (name is in Tbilisi time)."""
    local = label_utc.astimezone(SOURCE_TZ)
    return f"GSE_EXPORT_NEW_PERIOD_03M_{local:%d%m%Y_%H%M}.XML"
