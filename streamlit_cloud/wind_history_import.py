"""Deterministic import of the owner's wind-generation workbook (Issue #52).

The workbook ``qaris_sadgurebis_gamomushaveba_2016_2026.xlsx`` is read, never modified. Only typed
cell values are used: the workbook's formulas (row/column sums, averages, the Kartli+Zemo total)
carry no cached results, so every total is recomputed here from the monthly values.

Layout validated on 2026-11-20 (sha256 recorded in the seed's ``import_report.json``):

* sheet 1 ``ქართლის ქარი``: years in A5:A15, January-December in B:M (Kartli);
* sheet 2 ``ზემო ქარი და სულ ქარი``: row 6 is Zemo 2026, January-December in C:N;
* sheet 3 ``სრული ბაზა (ანალიტიკა)``: one row per month from row 2: A year, B month,
  D Kartli, E Zemo.

Sheet 3 is the primary source; every value is cross-checked against sheets 1 and 2. A zero in
sheet 3 whose station sheet leaves that month blank is a placeholder (the farm was not yet
reporting) and is not imported; a zero the station sheet also shows is a reported zero.

Usage: ``python wind_history_import.py WORKBOOK.xlsx --out history_seed``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from defusedxml import ElementTree

from wind_history import OWNER, Archive, Observation, sources_json

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
SHEETS = ("ქართლის ქარი", "ზემო ქარი და სულ ქარი", "სრული ბაზა (ანალიტიკა)")
COLS = "ABCDEFGHIJKLMNOP"
IMPORTER_VERSION = "workbook-import/1"
DOCUMENT_ID = "qaris_sadgurebis_gamomushaveba_2016_2026.xlsx"


class WorkbookError(ValueError):
    pass


def read_cells(path: Path) -> dict[str, dict[str, tuple[str | None, bool]]]:
    """``{sheet: {cell: (typed value text, has_formula)}}`` via the stdlib (no openpyxl)."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        book = ElementTree.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target")
                for r in ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        out = {}
        for sheet in book.find("m:sheets", NS):
            target = rels[sheet.get(f"{{{NS['r']}}}id")].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            cells = {}
            for c in ElementTree.fromstring(z.read(target)).iter(f"{{{NS['m']}}}c"):
                v, f = c.find("m:v", NS), c.find("m:f", NS)
                val = v.text if v is not None else None
                if c.get("t") == "s" and val is not None:
                    val = shared[int(val)]
                cells[c.get("r")] = (val, f is not None)
            out[sheet.get("name")] = cells
    return out


def _num(cells: dict, ref: str) -> tuple[float, int] | None:
    val, _formula = cells.get(ref, (None, False))
    if val is None or val == "":
        return None
    if not re.fullmatch(r"-?\d+(\.\d+)?(E-?\d+)?", val):
        raise WorkbookError(f"{ref}: non-numeric value {val!r}")
    number = float(val)
    if "E" in val:
        decimals = 6
    else:
        decimals = len(val.split(".")[1]) if "." in val else 0
    return round(number, 6), min(decimals, 6)


def extract(cells: dict) -> tuple[list[tuple[str, int, int, float, int, str]], list[str]]:
    """Return ``[(station_id, year, month, energy, decimals, note)]`` plus documented findings."""
    if tuple(cells) != SHEETS:
        raise WorkbookError(f"unexpected sheets {tuple(cells)!r}")
    kartli_sheet, zemo_sheet, base = (cells[name] for name in SHEETS)
    findings: list[str] = []
    kartli: dict[tuple[int, int], tuple[float, int]] = {}
    for row in range(5, 16):
        year = _num(kartli_sheet, f"A{row}")
        if year is None:
            raise WorkbookError(f"sheet 1 A{row}: year missing")
        for month in range(1, 13):
            value = _num(kartli_sheet, f"{COLS[month]}{row}")
            if value is not None:
                kartli[(int(year[0]), month)] = value
    zemo: dict[tuple[int, int], tuple[float, int]] = {}
    if _num(zemo_sheet, "B6") != (2026.0, 0):
        raise WorkbookError("sheet 2 B6 must be the Zemo 2026 row")
    for month in range(1, 13):
        value = _num(zemo_sheet, f"{COLS[month + 1]}6")
        if value is not None:
            zemo[(2026, month)] = value
    out = []
    seen = set()
    placeholders: dict[str, list[tuple[int, int]]] = {}
    row = 2
    while (year := _num(base, f"A{row}")) is not None:
        month = _num(base, f"B{row}")
        if month is None or not 1 <= month[0] <= 12:
            raise WorkbookError(f"sheet 3 B{row}: bad month")
        key = (int(year[0]), int(month[0]))
        if key in seen:
            raise WorkbookError(f"sheet 3 row {row}: duplicate month {key}")
        if seen and key != _next(max(seen)):
            raise WorkbookError(f"sheet 3 row {row}: {key} breaks the monthly sequence")
        seen.add(key)
        for col, station, ref in (("D", "kartli-gori", kartli), ("E", "zemo-wind", zemo)):
            value = _num(base, f"{col}{row}")
            other = ref.get(key)
            if value is None:
                if other is not None:
                    raise WorkbookError(f"{station} {key}: in station sheet but blank in sheet 3")
                continue
            if other is None:
                if value[0] == 0:
                    placeholders.setdefault(station, []).append(key)
                    continue
                raise WorkbookError(f"{station} {key}: value {value[0]} missing from station sheet")
            if abs(other[0] - value[0]) > 1e-9:
                raise WorkbookError(f"{station} {key}: sheet 3 {value[0]} != station sheet {other[0]}")
            note = "reported zero (commissioning month)" if value[0] == 0 else ""
            out.append((station, key[0], key[1], value[0], value[1], note))
        row += 1
    missing = (set(kartli) - seen) | (set(zemo) - seen)
    if missing:
        raise WorkbookError(f"station-sheet months absent from sheet 3: {sorted(missing)}")
    for station, keys in placeholders.items():
        first, last = min(keys), max(keys)
        findings.append(f"{station} {first[0]}-{first[1]:02d}..{last[0]}-{last[1]:02d}: {len(keys)} "
                        "sheet-3 zeros with a blank station sheet are placeholders - not imported")
    return out, findings


def _next(key: tuple[int, int]) -> tuple[int, int]:
    year, month = key
    return (year + 1, 1) if month == 12 else (year, month + 1)


def annual_totals(rows) -> dict[str, dict[int, dict]]:
    totals: dict[str, dict[int, dict]] = {}
    for station, year, month, energy, _dec, _note in rows:
        entry = totals.setdefault(station, {}).setdefault(year, {"gwh": 0.0, "months": []})
        entry["gwh"] = round(entry["gwh"] + energy, 6)
        entry["months"].append(month)
    for station in totals.values():
        for entry in station.values():
            entry["complete"] = sorted(entry["months"]) == list(range(1, 13))
            entry["gwh"] = round(entry["gwh"], 2)
    return totals


def build_seed(path: Path, imported_at: datetime, document_id: str | None = None) -> tuple[Archive, dict]:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    rows, findings = extract(read_cells(path))
    stamp = imported_at.astimezone(UTC).isoformat(timespec="seconds")
    document_id = document_id or path.name
    archive = Archive.empty()
    for station, year, month, energy, decimals, note in rows:
        archive.apply(Observation(station, year, month, energy, decimals, "owner_workbook", "",
                                  document_id, sha, stamp, note=note), imported_at, initial_status=OWNER)
    report = {
        "importer": IMPORTER_VERSION, "workbook": document_id, "sha256": sha, "bytes": len(raw),
        "imported_at": stamp, "sheets": list(SHEETS), "records": len(rows),
        "verification_status": OWNER, "findings": findings,
        "assumptions": [
            "Values are GWh (the workbook follows the GSE balance unit, million kWh).",
            "Formulas carry no cached values; all totals are recomputed from monthly cells.",
            "Sheet-3 zeros without a station-sheet value are placeholders, not observations.",
            "Kartli October 2016 is a reported zero (the GSE 2016 balance also prints 0).",
        ],
        "annual_totals": annual_totals(rows),
    }
    return archive, report


def write_seed(out: Path, archive: Archive, report: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    records, ledger = archive.dump()
    (out / "wind_monthly.csv").write_text(records, encoding="utf-8")
    (out / "wind_monthly_revisions.csv").write_text(ledger, encoding="utf-8")
    (out / "import_report.json").write_text(sources_json(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workbook", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--imported-at", default=None, help="ISO timestamp (default: now, UTC)")
    ap.add_argument("--document-id", default=DOCUMENT_ID, help="canonical workbook name")
    args = ap.parse_args(argv)
    when = datetime.fromisoformat(args.imported_at) if args.imported_at else datetime.now(UTC)
    try:
        archive, report = build_seed(args.workbook, when, args.document_id)
    except WorkbookError as exc:
        print(f"workbook refused: {exc}", file=sys.stderr)
        return 1
    write_seed(args.out, archive, report)
    print(json.dumps({k: report[k] for k in ("records", "sha256", "findings")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
