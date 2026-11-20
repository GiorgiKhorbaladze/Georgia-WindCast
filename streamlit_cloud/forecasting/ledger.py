"""Append-only forecast ledger: ``ledger/YYYY/MM/YYYY-MM-DD.csv.gz`` by UTC issue date.

Each append adds a gzip member (multi-member gzip is a valid stream), so earlier bytes are never
rewritten; compression keeps a year of 15-minute issues well under the free repository limits.

Rows are never edited or deleted. Every row carries a SHA-256 of its own content, checked on
every read; a second record with an existing key is refused instead of overwriting the first.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from forecasting.contract import ContractError, ForecastRecord, parse, render, row_of, validate


def day_path(root: Path, rec: ForecastRecord) -> Path:
    d = rec.issued_at_utc.date()
    return root / "ledger" / f"{d:%Y}" / f"{d:%m}" / f"{d.isoformat()}.csv.gz"


def _read(path: Path) -> str:
    return gzip.decompress(path.read_bytes()).decode("utf-8")


def read_all(root: Path) -> list[ForecastRecord]:
    out: list[ForecastRecord] = []
    for path in sorted((root / "ledger").rglob("*.csv.gz")):
        out.extend(parse(_read(path)))
    return out


def append(root: Path, records: list[ForecastRecord]) -> int:
    """Validate and append; returns the number of new rows. Existing rows are byte-identical after."""
    by_file: dict[Path, list[ForecastRecord]] = {}
    for rec in records:
        validate(rec)
        by_file.setdefault(day_path(root, rec), []).append(rec)
    added = 0
    for path, new in by_file.items():
        existing = parse(_read(path)) if path.exists() else []
        keys = {r.key for r in existing}
        fresh = []
        for rec in new:
            if rec.key in keys:
                raise ContractError(f"ledger already holds {rec.key}; records are immutable")
            keys.add(rec.key)
            fresh.append(rec)
        if not fresh:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        text = render(fresh)
        if existing:
            text = text.split("\n", 1)[1]  # header only once, in the first member
        with gzip.GzipFile(path, "ab", mtime=0) as fh:  # mtime=0: identical input -> identical bytes
            fh.write(text.encode("utf-8"))
        added += len(fresh)
    return added


__all__ = ["append", "day_path", "read_all", "row_of"]
