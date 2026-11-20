"""Official GSE yearly electricity balances: discovery, PDF parsing and the three-day monitor.

Source: the GSE "ფაქტიური ბალანსი" (Actual balance) page. Its document links are discovered from
the page's own content API at every check (``admin.gse.com.ge/api/ka/menu/<slug>``); no document
URL is hard-coded or guessed. Each yearly PDF is one page exported from a spreadsheet, values in
million kWh (= GWh), months January-December plus a total column.

The monitor contacts GSE at most once every 72 hours, counted from the previous *attempt*
(persisted ``last_attempt_at``, whether it succeeded or not); earlier scheduled wake-ups log
``skipped_not_due`` and make no request. A manual ``--force`` run is the only exception. Documents are fetched conditionally (ETag /
Last-Modified) and compared by SHA-256, so an unchanged document is never re-parsed. Every value
change goes through :class:`wind_history.Archive`, which never overwrites silently.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from wind_history import (
    PENDING,
    Archive,
    Observation,
    is_total_label,
    looks_like_wind_station,
    sources_json,
    station_for,
    tolerance,
)

PAGE_API = "https://admin.gse.com.ge/api/ka/menu/faqtiuri-balansi-125"
PAGE_PUBLIC = "https://gse.com.ge/momkhmareblebistvis/monatsemebi-elektroenergetikuli-sistemidan/faqtiuri-balansi"
ALLOWED_HOSTS = ("admin.gse.com.ge",)
FIRST_YEAR = 2016  # first year with a wind farm in the balance (Kartli, October 2016)
MIN_INTERVAL = timedelta(hours=72)
MAX_PDF_BYTES = 5_000_000
PARSER_VERSION = "gse-balance-pdf/1"
MONTH_TOKENS = ("ianvari", "Tebervali", "marti", "aprili", "maisi", "ivnisi", "ivlisi", "agvisto",
                "seqtemberi", "oqtomberi", "noemberi", "dekemberi", "sul")

# Per-document states reported by the monitor.
UNCHANGED, NEW, UPDATED, MISSING = "unchanged", "new", "updated", "missing"
DOWNLOAD_FAILED, UNSUPPORTED, INVALID = "download_failed", "unsupported_structure", "validation_failed"
DOC_STATES = (UNCHANGED, NEW, UPDATED, MISSING, DOWNLOAD_FAILED, UNSUPPORTED, INVALID)


class StructureError(ValueError):
    """The document is not laid out as a GSE yearly balance this parser understands."""


class BalanceValidationError(ValueError):
    """The document parsed, but its numbers are not internally consistent."""


# --- discovery -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Document:
    year: int
    file_id: str
    url: str


def discover(page: dict) -> list[Document]:
    """Yearly PDFs listed on the official page, from the page JSON itself (no guessed URLs)."""
    try:
        contents = page["data"]["contents"]
    except (KeyError, TypeError) as exc:
        raise StructureError("page JSON has no data.contents") from exc
    docs: dict[int, Document] = {}
    for block in contents:
        for item in block.get("files") or []:
            name, url = str(item.get("name", "")).strip(), str(item.get("path", ""))
            if not re.fullmatch(r"(19|20)\d{2}", name):
                continue
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS \
                    or not parsed.path.lower().endswith(".pdf"):
                continue  # never follow a link off the official host
            year = int(name)
            if year in docs:
                raise StructureError(f"page lists year {year} twice")
            docs[year] = Document(year, str(item.get("id", "")), url)
    if not docs:
        raise StructureError("no yearly balance documents on the page")
    return [docs[y] for y in sorted(docs)]


# --- PDF layout parsing --------------------------------------------------------------------
NUMBER = re.compile(r"\d{1,3}(?:[ ,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


@dataclass
class ParsedBalance:
    year: int
    decimal: str  # "." or ","
    stations: dict[str, dict[int, tuple[float, int]]] = field(default_factory=dict)
    totals: dict[str, tuple[float, int]] = field(default_factory=dict)  # station -> printed total
    wind_total: dict[int, tuple[float, int]] | None = None
    unknown_rows: list[str] = field(default_factory=list)


def pdf_to_layout_text(pdf: bytes, workdir: Path) -> str:
    exe = shutil.which("pdftotext")
    if exe is None:
        raise StructureError("pdftotext (poppler-utils) is not installed")
    src = workdir / "doc.pdf"
    src.write_bytes(pdf)
    run = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(src), "-"], capture_output=True,
                         timeout=60, check=False)
    if run.returncode != 0:
        raise StructureError(f"pdftotext failed ({run.returncode})")
    return run.stdout.decode("utf-8", errors="strict")


def _decimal_style(text: str) -> str:
    dot = len(re.findall(r"(?<![\d.,])\d{1,3}(?:,\d{3})*\.\d+(?![\d.,])", text))
    comma = len(re.findall(r"(?<![\d.,])\d{1,3}(?: \d{3})*,\d{1,3}(?![\d.,])", text))
    if dot == comma:
        raise StructureError("cannot tell the decimal separator")
    return "." if dot > comma else ","


def _value(token: str, decimal: str) -> tuple[float, int]:
    if decimal == ".":
        clean = token.replace(",", "")
        if " " in clean:
            raise StructureError(f"unexpected token {token!r}")
    else:
        if "." in token:
            raise StructureError(f"unexpected token {token!r}")
        clean = token.replace(" ", "").replace(",", ".")
    decimals = len(clean.split(".")[1]) if "." in clean else 0
    return float(clean), decimals


def parse_balance_text(text: str, expected_year: int) -> ParsedBalance:
    lines = text.splitlines()
    title = next((m for line in lines if (m := re.search(r"balansi\s+((?:19|20)\d{2})\s+wlis", line))), None)
    if title is None:
        raise StructureError("balance title not found")
    if int(title.group(1)) != expected_year:
        raise StructureError(f"document is for {title.group(1)}, listed as {expected_year}")
    header = next((line for line in lines if all(t in line for t in MONTH_TOKENS)), None)
    if header is None:
        raise StructureError("month header not found")
    centres = [header.index(t) + len(t) / 2 for t in MONTH_TOKENS]
    if centres != sorted(centres):
        raise StructureError("month header out of order")
    result = ParsedBalance(expected_year, _decimal_style(text))
    for line in lines:
        m = re.match(r"^(\S.*?)(?:\s{2,}|$)", line)
        if not m:
            continue
        label = m.group(1)
        station = station_for(label)
        total = is_total_label(label)
        if station is None and not total:
            if looks_like_wind_station(label):
                result.unknown_rows.append(label)
            continue
        cells: dict[int, tuple[float, int]] = {}
        for tok in NUMBER.finditer(line, m.end(1)):
            centre = (tok.start() + tok.end()) / 2
            col = min(range(len(centres)), key=lambda i: abs(centres[i] - centre))
            if col in cells:
                raise StructureError(f"{label}: two values under {MONTH_TOKENS[col]}")
            cells[col] = _value(tok.group(), result.decimal)
        months = {c + 1: v for c, v in cells.items() if c < 12}
        if total:
            result.wind_total = months
            continue
        if station in result.stations:
            raise StructureError(f"{label}: station listed twice")
        if 12 not in cells:
            raise BalanceValidationError(f"{label}: annual total missing")
        result.stations[station] = months
        result.totals[station] = cells[12]
    if result.unknown_rows:
        raise StructureError(f"unregistered wind station rows: {result.unknown_rows}")
    validate_balance(result)
    return result


def validate_balance(b: ParsedBalance) -> None:
    for station, months in b.stations.items():
        if not months:
            raise BalanceValidationError(f"{station}: total without monthly values")
        total, tdec = b.totals[station]
        decs = [d for _v, d in months.values()]
        allowed = len(months) * tolerance(*decs) + tolerance(tdec)
        if abs(sum(v for v, _d in months.values()) - total) > allowed:
            raise BalanceValidationError(f"{station}: months sum to {sum(v for v, _ in months.values()):.4f}, "
                                         f"total printed {total}")
        for month, (value, _d) in months.items():
            if value < 0 or value > 400:
                raise BalanceValidationError(f"{station} {month}: implausible {value} GWh")
    if b.wind_total is not None:
        for month, (value, dec) in b.wind_total.items():
            parts = [b.stations[s][month] for s in b.stations if month in b.stations[s]]
            allowed = len(parts) * tolerance(*(d for _v, d in parts), dec) + tolerance(dec) if parts else tolerance(dec)
            if abs(sum(v for v, _d in parts) - value) > allowed:
                raise BalanceValidationError(f"wind total {month}: stations {sum(v for v, _ in parts):.2f} "
                                             f"!= printed {value} (unregistered or missing station?)")
        extra = {m for s in b.stations.values() for m in s} - set(b.wind_total)
        if extra:
            raise BalanceValidationError(f"station values in months without a wind total: {sorted(extra)}")


def observations(b: ParsedBalance, doc: Document, sha: str, retrieved_at: str, published_at: str) -> list[Observation]:
    return [
        Observation(station, b.year, month, value, dec, "gse_balance_pdf", doc.url,
                    f"gse-balance-{b.year}#{doc.file_id}", sha, retrieved_at, published_at,
                    "reported zero" if value == 0 else "")
        for station, months in sorted(b.stations.items()) for month, (value, dec) in sorted(months.items())
    ]


# --- archive I/O and monitor ---------------------------------------------------------------
FILES = ("wind_monthly.csv", "wind_monthly_revisions.csv")


def load_archive(directory: Path, seed: Path) -> tuple[Archive, bool]:
    """Read ``history/`` from the data-branch checkout; bootstrap it from the reviewed seed once."""
    if all((directory / name).exists() for name in FILES):
        texts = [(directory / name).read_text(encoding="utf-8") for name in FILES]
        return Archive.load(*texts), False
    if any((directory / name).exists() for name in FILES):
        raise StructureError("history archive is incomplete; refusing to re-seed over it")
    texts = [(seed / name).read_text(encoding="utf-8") for name in FILES]
    return Archive.load(*texts), True


def save_archive(directory: Path, archive: Archive) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in zip(FILES, archive.dump(), strict=True):
        tmp = directory / f".{name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(directory / name)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="seconds")


def due(state: dict, now: datetime, force: bool = False) -> bool:
    last = state.get("last_attempt_at")
    return force or not last or now - datetime.fromisoformat(last) >= MIN_INTERVAL


@dataclass
class Fetched:
    status: int
    body: bytes = b""
    etag: str = ""
    last_modified: str = ""


Fetch = Callable[[str, dict[str, str]], Fetched]


def check(directory: Path, seed: Path, fetch: Fetch, now: datetime, workdir: Path,
          *, force: bool = False, to_text: Callable[[bytes, Path], str] = pdf_to_layout_text) -> dict:
    """One monitor run. Returns a report; writes the archive only when something changed."""
    state_path, sources_path = directory / "monitor_state.json", directory / "sources.json"
    state = _read_json(state_path)
    report: dict = {"run_at": _iso(now), "parser": PARSER_VERSION, "documents": {}, "changes": {}}
    if not due(state, now, force):
        nxt = datetime.fromisoformat(state["last_attempt_at"]) + MIN_INTERVAL
        report.update(result="skipped_not_due", next_check_after=_iso(nxt))
        return report
    archive, seeded = load_archive(directory, seed)
    start = len(archive.ledger)
    sources = _read_json(sources_path)
    state["last_attempt_at"] = _iso(now)
    report["next_check_after"] = _iso(now + MIN_INTERVAL)
    _write_json(state_path, state)  # the attempt counts even if the request below fails
    try:
        page = fetch(PAGE_API, {"Accept": "application/json"})
    except Exception as exc:
        state["last_result"] = report["result"] = f"discovery_failed: {type(exc).__name__}"
        _write_json(state_path, state)
        return report
    try:
        if page.status != 200:
            raise StructureError(f"page API answered {page.status}")
        docs = [d for d in discover(json.loads(page.body)) if d.year >= FIRST_YEAR]
        state["last_page_sha256"] = hashlib.sha256(page.body).hexdigest()
    except (StructureError, ValueError) as exc:
        # The page could not be read: nothing is inferred; retry at the next wake-up.
        state["last_result"] = report["result"] = f"discovery_failed: {exc}"
        _write_json(state_path, state)
        if seeded:
            save_archive(directory, archive)
        return report
    listed = {str(d.year) for d in docs}
    for key, entry in sources.items():
        if key not in listed and entry.get("state") != MISSING:
            entry.update(state=MISSING, missing_since=_iso(now))
            report["documents"][key] = MISSING
    for doc in docs:
        key, prior = str(doc.year), sources.get(str(doc.year), {})
        report["documents"][key] = _check_document(doc, prior, archive, fetch, now, workdir, to_text, report)
        sources[key] = prior
    state.update(last_success_at=_iso(now), last_result="ok")
    report["result"] = "checked"
    report["flags"] = large_changes(archive, start)
    report["pending_approval"] = sum(1 for r in archive.records.values() if r.verification_status == PENDING
                                     or r.pending_revision_id is not None)
    save_archive(directory, archive)
    (directory / "sources.json").write_text(sources_json(sources), encoding="utf-8")
    _write_json(state_path, state)
    return report


LARGE_CHANGE = 0.10  # relative change of an existing value that is flagged for review


def large_changes(archive: Archive, start: int) -> list[str]:
    """Ledger entries of this run that would change an existing value by more than 10 %."""
    out = []
    for rev in archive.ledger[start:]:
        if rev.old_energy is None or rev.new_energy is None or rev.action not in ("conflict", "revise_pending"):
            continue
        base = max(abs(rev.old_energy), 0.01)
        if abs(rev.new_energy - rev.old_energy) / base > LARGE_CHANGE:
            out.append(f"{rev.station_id} {rev.year}-{rev.month:02d}: {rev.old_energy} -> {rev.new_energy} GWh "
                       f"(revision {rev.revision_id})")
    return out


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sources_json(data), encoding="utf-8")


def _check_document(doc, prior, archive, fetch, now, workdir, to_text, report) -> str:
    stamp = _iso(now)
    headers = {}
    if prior.get("url") == doc.url:
        if prior.get("etag"):
            headers["If-None-Match"] = prior["etag"]
        if prior.get("last_modified"):
            headers["If-Modified-Since"] = prior["last_modified"]
    prior.update(file_id=doc.file_id, url=doc.url, last_checked_at=stamp)
    prior.setdefault("first_seen_at", stamp)
    try:
        got = fetch(doc.url, headers)
    except Exception as exc:  # network errors keep the previous state and data
        prior.update(state=DOWNLOAD_FAILED, error=type(exc).__name__)
        return DOWNLOAD_FAILED
    if got.status == 304 and prior.get("sha256"):
        prior.update(state=UNCHANGED)
        return UNCHANGED
    if got.status != 200 or not got.body or len(got.body) > MAX_PDF_BYTES or not got.body.startswith(b"%PDF"):
        prior.update(state=DOWNLOAD_FAILED, error=f"http {got.status}, {len(got.body)} bytes")
        return DOWNLOAD_FAILED
    sha = hashlib.sha256(got.body).hexdigest()
    prior.update(etag=got.etag, last_modified=got.last_modified, bytes=len(got.body))
    if sha == prior.get("sha256") and prior.get("parser") == PARSER_VERSION:
        prior.update(state=UNCHANGED)
        return UNCHANGED
    kind = UPDATED if prior.get("sha256") else NEW
    try:
        parsed = parse_balance_text(to_text(got.body, workdir), doc.year)
    except StructureError as exc:
        prior.update(state=UNSUPPORTED, error=str(exc)[:300], rejected_sha256=sha)
        return UNSUPPORTED
    except BalanceValidationError as exc:
        prior.update(state=INVALID, error=str(exc)[:300], rejected_sha256=sha)
        return INVALID
    changes = report["changes"]
    for obs in observations(parsed, doc, sha, stamp, got.last_modified):
        outcome = archive.apply(obs, now, initial_status=PENDING)
        changes[outcome] = changes.get(outcome, 0) + 1
    if prior.get("sha256") and prior["sha256"] != sha:
        prior.setdefault("history", []).append({"sha256": prior["sha256"], "replaced_at": stamp})
    prior.update(state=kind, sha256=sha, parser=PARSER_VERSION, error="", rejected_sha256="")
    return kind
