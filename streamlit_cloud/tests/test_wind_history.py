"""Issue #52 backend: workbook import, archive/ledger, GSE PDF parsing and the 72-hour monitor.

Offline only. PDF tests use trimmed ``pdftotext -layout`` extracts of the genuine GSE yearly
balance PDFs (2016 dot-decimal, 2020 comma-decimal, 2026 multi-station with a wind total row);
the page fixture is the genuine GSE page JSON. No request leaves the process.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gse_balance as gb
import wind_history as wh
import wind_history_import as wi

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "gse_balance"
SEED = HERE.parent / "history_seed"
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def text(year: int) -> str:
    return (FIX / f"{year}.txt").read_text(encoding="utf-8")


# --- station alias registry ----------------------------------------------------------------
def test_aliases_map_both_kartli_spellings_and_reject_unknown_names():
    assert wh.station_for("ქართლის ქარის ელ.სადგური") == "kartli-gori"
    assert wh.station_for("ქართლის  ქარის   ელექტროსადგური") == "kartli-gori"
    assert wh.station_for("რუისის ქარის ელექტროსადგური") == "ruisi"
    assert wh.station_for("ახალი ქარის ელექტროსადგური") is None  # no fuzzy matching
    assert wh.is_total_label("სულ ქარის სადგურები")
    assert not wh.looks_like_wind_station("საქართველოს მოხმარება")  # contains "ქარ", not a farm
    assert wh.looks_like_wind_station("ახალი ქარის ელექტროსადგური")


# --- GSE PDF layout parser (genuine extracts) ----------------------------------------------
def test_parse_2016_dot_decimal_partial_year_with_reported_zero():
    b = gb.parse_balance_text(text(2016), 2016)
    assert b.decimal == "."
    assert b.stations == {"kartli-gori": {10: (0.0, 0), 11: (1.83474, 5), 12: (7.19098, 5)}}
    assert b.totals["kartli-gori"] == (9.0, 1)  # months 1-9 blank: not reported, no rows


def test_parse_2020_comma_decimal_full_year():
    b = gb.parse_balance_text(text(2020), 2020)
    assert b.decimal == ","
    months = b.stations["kartli-gori"]
    assert sorted(months) == list(range(1, 13))
    assert months[1] == (7.91, 2) and months[12] == (7.07, 2)
    assert round(sum(v for v, _ in months.values()), 2) == 90.84


def test_parse_2026_three_stations_and_wind_total_cross_check():
    b = gb.parse_balance_text(text(2026), 2026)
    assert set(b.stations) == {"kartli-gori", "zemo-wind", "ruisi"}
    assert sorted(b.stations["zemo-wind"]) == list(range(3, 11))
    assert b.stations["ruisi"] == {9: (0.31, 2), 10: (33.27, 2)}
    assert b.wind_total[10] == (43.75, 2)
    assert 11 not in b.stations["kartli-gori"]  # Nov/Dec not yet published: absent, not zero


def test_wrong_year_and_missing_header_are_unsupported_structure():
    with pytest.raises(gb.StructureError):
        gb.parse_balance_text(text(2020), 2021)
    with pytest.raises(gb.StructureError):
        gb.parse_balance_text(text(2020).replace("dekemberi", "dec"), 2020)
    with pytest.raises(gb.StructureError):
        gb.parse_balance_text("<html>captcha</html>", 2020)


def test_unregistered_wind_station_is_quarantined_not_imported():
    extra = text(2026) + "ახალი ქარის ელექტროსადგური            1,00\n"
    with pytest.raises(gb.StructureError, match="unregistered"):
        gb.parse_balance_text(extra, 2026)


def test_inconsistent_total_fails_validation():
    bad = text(2020).replace("90,8", "95,8")
    with pytest.raises(gb.BalanceValidationError):
        gb.parse_balance_text(bad, 2020)


def test_station_rows_must_add_up_to_published_wind_total():
    bad = text(2026).replace("43,75", "53,75", 1)
    with pytest.raises(gb.BalanceValidationError, match="wind total"):
        gb.parse_balance_text(bad, 2026)


# --- discovery -----------------------------------------------------------------------------
def test_discovery_uses_page_links_only_and_rejects_off_host_links():
    page = json.loads((FIX / "page_ka.json").read_text(encoding="utf-8"))
    docs = gb.discover(page)
    assert [d.year for d in docs] == list(range(1995, 2027))  # " 2006" is normalised
    assert all(d.url.startswith("https://admin.gse.com.ge/") for d in docs)
    page["data"]["contents"][0]["files"].append({"id": 1, "name": "2027", "path": "https://evil.example/x.pdf"})
    assert 2027 not in [d.year for d in gb.discover(page)]
    with pytest.raises(gb.StructureError):
        gb.discover({"data": {"contents": []}})


# --- workbook importer ---------------------------------------------------------------------
def _xlsx(sheets: dict[str, dict[str, str]]) -> bytes:
    """Minimal workbook in the owner's layout (typed values only)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="r{i}"/>' for i, n in enumerate(sheets, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="r{i}" Target="worksheets/s{i}.xml" Type="x"/>' for i in range(1, len(sheets) + 1))
                   + "</Relationships>")
        for i, cells in enumerate(sheets.values(), 1):
            body = "".join(f'<c r="{ref}"><v>{val}</v></c>' for ref, val in cells.items())
            z.writestr(f"xl/worksheets/s{i}.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       f"<sheetData><row>{body}</row></sheetData></worksheet>")
    return buf.getvalue()


def _owner_layout(zemo_march="3.95", base_kartli_override=None):
    s1 = {f"A{r}": str(2011 + r) for r in range(5, 16)}
    s1.update({"K5": "0", "L5": "1.83", "M5": "7.19"})
    s1.update({f"{wi.COLS[m]}{r}": "6.5" for r in range(6, 15) for m in range(1, 13)})
    s1.update({f"{wi.COLS[m]}15": "5.0" for m in range(1, 8)})
    s2 = {"B6": "2026", **({"E6": zemo_march} if zemo_march else {})}
    s3, row = {}, 2
    for y in range(2016, 2027):
        for m in range(10 if y == 2016 else 1, 13 if y < 2026 else 8):
            s3[f"A{row}"], s3[f"B{row}"] = str(y), str(m)
            s3[f"D{row}"] = s1.get(f"{wi.COLS[m]}{y - 2011}", "")
            s3[f"E{row}"] = zemo_march if (y, m) == (2026, 3) and zemo_march else "0"
            row += 1
    if base_kartli_override:
        s3["D3"] = base_kartli_override
    return {wi.SHEETS[0]: s1, wi.SHEETS[1]: s2, wi.SHEETS[2]: s3}


def test_workbook_import_recomputes_totals_and_skips_placeholder_zeros(tmp_path):
    path = tmp_path / "wb.xlsx"
    path.write_bytes(_xlsx(_owner_layout()))
    archive, report = wi.build_seed(path, T0, "wb.xlsx")
    keys = set(archive.records)
    assert len(keys) == 118 + 1  # every Kartli month plus Zemo March 2026
    assert ("zemo-wind", 2026, 2) not in keys  # sheet-3 zero, blank station sheet: placeholder
    assert archive.records[("kartli-gori", 2016, 10)].energy == 0.0  # explicit reported zero
    assert report["annual_totals"]["kartli-gori"][2016] == {"gwh": 9.02, "months": [10, 11, 12], "complete": False}
    assert report["annual_totals"]["kartli-gori"][2017]["complete"] is True
    assert {r.verification_status for r in archive.records.values()} == {wh.OWNER}


def test_workbook_cross_sheet_mismatch_is_refused(tmp_path):
    path = tmp_path / "wb.xlsx"
    path.write_bytes(_xlsx(_owner_layout(base_kartli_override="1.84")))
    with pytest.raises(wi.WorkbookError, match="!="):
        wi.build_seed(path, T0)


def test_workbook_import_is_deterministic_and_idempotent(tmp_path):
    path = tmp_path / "wb.xlsx"
    path.write_bytes(_xlsx(_owner_layout()))
    a1, _ = wi.build_seed(path, T0)
    a2, _ = wi.build_seed(path, T0)
    assert a1.dump() == a2.dump()
    rows, _ = wi.extract(wi.read_cells(path))
    before = a1.dump()
    for st, y, m, e, d, _note in rows:  # re-import into the same archive changes nothing
        assert a1.apply(wh.Observation(st, y, m, e, d, "owner_workbook", "", "wb.xlsx",
                                       a1.records[(st, y, m)].source_sha256, ""), T0,
                        initial_status=wh.OWNER) == "unchanged"
    assert a1.dump() == before


def test_committed_seed_matches_owner_figures():
    archive = wh.Archive.load(*(p.read_text(encoding="utf-8") for p in (SEED / "wind_monthly.csv",
                                                                        SEED / "wind_monthly_revisions.csv")))
    report = json.loads((SEED / "import_report.json").read_text(encoding="utf-8"))
    assert report["sha256"] == "dd3466701c670ef3cb4c6a8181dda156dbd4e658f85a884409a5f652e28f4311"
    assert len(archive.records) == report["records"] == 123
    kartli = [r for r in archive.records.values() if r.station_id == "kartli-gori"]
    assert len(kartli) == 118
    annual = {y: round(sum(r.energy for r in kartli if r.year == y), 2) for y in range(2017, 2026)}
    assert list(annual.values()) == [87.74, 84.28, 84.70, 90.84, 83.36, 87.50, 86.11, 77.57, 79.41]
    jan_jul = lambda st, y: round(sum(r.energy for r in archive.records.values()  # noqa: E731
                                      if r.station_id == st and r.year == y and r.month <= 7), 2)
    assert (jan_jul("kartli-gori", 2025), jan_jul("kartli-gori", 2026), jan_jul("zemo-wind", 2026)) == (48.51, 47.27, 21.0)


# --- archive, ledger, revisions ------------------------------------------------------------
def obs(value, sha="s1", decimals=2, month=1, kind="gse_balance_pdf"):
    return wh.Observation("kartli-gori", 2025, month, value, decimals, kind, "https://admin.gse.com.ge/x.pdf",
                          "gse-balance-2025#1", sha, T0.isoformat())


def test_matching_official_value_verifies_owner_record():
    a = wh.Archive.empty()
    a.apply(obs(6.52, sha="wb", kind="owner_workbook"), T0, initial_status=wh.OWNER)
    assert a.apply(obs(6.52), T0, initial_status=wh.PENDING) == "verified"
    rec = a.records[("kartli-gori", 2025, 1)]
    assert rec.verification_status == wh.VERIFIED and rec.source_kind == "gse_balance_pdf"
    assert [r.action for r in a.ledger] == ["insert", "verify"]


def test_differing_official_value_is_quarantined_not_overwritten():
    a = wh.Archive.empty()
    a.apply(obs(6.52, sha="wb", kind="owner_workbook"), T0, initial_status=wh.OWNER)
    assert a.apply(obs(7.10), T0, initial_status=wh.PENDING) == "conflict"
    rec = a.records[("kartli-gori", 2025, 1)]
    assert rec.energy == 6.52 and rec.pending_energy == 7.10 and rec.verification_status == wh.CONFLICT
    assert a.apply(obs(7.10, sha="s2"), T0, initial_status=wh.PENDING) == "unchanged"  # not logged twice


def test_revision_of_verified_month_needs_approval_then_replaces_value():
    a = wh.Archive.empty()
    a.apply(obs(6.52, sha="wb", kind="owner_workbook"), T0, initial_status=wh.OWNER)
    a.apply(obs(6.52), T0, initial_status=wh.PENDING)
    assert a.apply(obs(6.80, sha="s2"), T0, initial_status=wh.PENDING) == "revision_pending"
    rec = a.records[("kartli-gori", 2025, 1)]
    assert (rec.energy, rec.verification_status, rec.pending_energy) == (6.52, wh.VERIFIED, 6.80)
    assert a.approve(T0, rec.pending_revision_id, "owner approved") == [("kartli-gori", 2025, 1)]
    rec = a.records[("kartli-gori", 2025, 1)]
    assert (rec.energy, rec.verification_status, rec.pending_energy, rec.source_sha256) == (6.80, wh.APPROVED, None, "s2")


def test_new_official_month_is_pending_and_hidden_until_approved():
    a = wh.Archive.empty()
    a.apply(obs(6.34, month=10), T0, initial_status=wh.PENDING)
    assert wh.public_records(a.records.values()) == []
    a.approve(T0, 1, "ok")
    assert [r.verification_status for r in wh.public_records(a.records.values())] == [wh.APPROVED]


def test_rounding_tolerance_uses_printed_precision():
    a = wh.Archive.empty()
    a.apply(obs(1.83, sha="wb", kind="owner_workbook"), T0, initial_status=wh.OWNER)
    assert a.apply(obs(1.83474, decimals=5), T0, initial_status=wh.PENDING) == "verified"
    b = wh.Archive.empty()
    b.apply(obs(1.83, sha="wb", kind="owner_workbook"), T0, initial_status=wh.OWNER)
    assert b.apply(obs(1.84, decimals=2), T0, initial_status=wh.PENDING) == "conflict"


def test_csv_round_trip_and_validation_rejects_bad_rows():
    a = wh.Archive.empty()
    a.apply(obs(6.52), T0, initial_status=wh.PENDING)
    records, ledger = a.dump()
    assert wh.Archive.load(records, ledger).dump() == (records, ledger)
    with pytest.raises(wh.HistoryFormatError, match="unit"):
        wh.parse_records(records.replace(",GWh,", ",MWh,"))
    with pytest.raises(wh.HistoryFormatError, match="duplicate"):
        wh.parse_records(records + records.splitlines()[1] + "\n")
    with pytest.raises(wh.HistoryFormatError, match="energy"):
        wh.parse_records(records.replace(",6.52,", ",6520.0,"))  # kWh/MWh unit slip
    with pytest.raises(wh.HistoryFormatError, match="increasing"):
        wh.parse_ledger(ledger + ledger.splitlines()[1] + "\n")


# --- monitor -------------------------------------------------------------------------------
class FakeGSE:
    def __init__(self, docs: dict[int, str]):
        self.page = json.loads((FIX / "page_ka.json").read_text(encoding="utf-8"))
        self.texts = docs
        self.urls = {d.url: d.year for d in gb.discover(self.page)}
        self.calls: list[tuple[str, dict]] = []
        self.status: dict[int, int] = {}
        self.page_status = 200

    def fetch(self, url, headers):
        self.calls.append((url, headers))
        if url == gb.PAGE_API:
            return gb.Fetched(self.page_status, json.dumps(self.page).encode())
        year = self.urls[url]
        if self.status.get(year):
            return gb.Fetched(self.status[year], b"<html>blocked</html>")
        if year not in self.texts:
            return gb.Fetched(404)
        if headers.get("If-None-Match") == f'"{hash(self.texts[year])}"':
            return gb.Fetched(304)
        return gb.Fetched(200, b"%PDF-" + self.texts[year].encode(), f'"{hash(self.texts[year])}"', "Thu, 19 Nov 2026 10:00:00 GMT")


def to_text(body, _workdir):
    return body[5:].decode()


def run(tmp_path, fake, now, force=False):
    return gb.check(tmp_path / "history", SEED, fake.fetch, now, tmp_path, force=force, to_text=to_text)


def test_monitor_first_run_verifies_seed_and_stages_new_months(tmp_path):
    fake = FakeGSE({2016: text(2016), 2020: text(2020), 2026: text(2026)})
    report = run(tmp_path, fake, T0)
    assert report["result"] == "checked"
    assert report["documents"]["2016"] == report["documents"]["2026"] == gb.NEW
    assert report["documents"]["2017"] == gb.DOWNLOAD_FAILED  # 404 here: kept, not inferred
    archive, _ = gb.load_archive(tmp_path / "history", SEED)
    recs = archive.records
    assert recs[("kartli-gori", 2016, 11)].verification_status == wh.VERIFIED
    assert recs[("kartli-gori", 2017, 1)].verification_status == wh.OWNER  # no document: unchanged
    assert recs[("ruisi", 2026, 10)].verification_status == wh.PENDING
    assert report["pending_approval"] == 8
    state = json.loads((tmp_path / "history" / "monitor_state.json").read_text())
    assert state["last_attempt_at"] == state["last_success_at"] == T0.isoformat()
    assert len(state["last_page_sha256"]) == 64


def test_monitor_skips_without_any_request_before_72_hours(tmp_path):
    fake = FakeGSE({2026: text(2026)})
    run(tmp_path, fake, T0)
    fake.calls.clear()
    report = run(tmp_path, fake, T0 + timedelta(hours=71, minutes=59))
    assert report["result"] == "skipped_not_due" and fake.calls == []
    assert run(tmp_path, fake, T0 + timedelta(hours=72))["result"] == "checked"


def test_failed_attempt_also_starts_the_72_hour_wait(tmp_path):
    fake = FakeGSE({})
    fake.page_status = 403
    assert run(tmp_path, fake, T0)["result"].startswith("discovery_failed")
    fake.calls.clear()
    assert run(tmp_path, fake, T0 + timedelta(hours=24))["result"] == "skipped_not_due"
    assert fake.calls == []
    assert run(tmp_path, fake, T0 + timedelta(hours=24), force=True)["result"].startswith("discovery_failed")


def test_unchanged_documents_use_conditional_requests_and_change_nothing(tmp_path):
    fake = FakeGSE({2026: text(2026)})
    run(tmp_path, fake, T0)
    before = (tmp_path / "history" / "wind_monthly_revisions.csv").read_text()
    fake.calls.clear()
    report = run(tmp_path, fake, T0 + timedelta(hours=73))
    assert report["documents"]["2026"] == gb.UNCHANGED and report["changes"] == {}
    sent = dict(fake.calls)[next(u for u, y in fake.urls.items() if y == 2026)]
    assert "If-None-Match" in sent and "If-Modified-Since" in sent
    assert (tmp_path / "history" / "wind_monthly_revisions.csv").read_text() == before


def test_republished_document_revising_earlier_month_is_held_for_approval(tmp_path):
    fake = FakeGSE({2020: text(2020)})
    run(tmp_path, fake, T0)
    fake.texts[2020] = text(2020).replace("7,91", "8,91").replace("90,8", "91,8")
    report = run(tmp_path, fake, T0 + timedelta(days=3))
    assert report["documents"]["2020"] == gb.UPDATED
    assert report["changes"].get("revision_pending") == 1
    assert report["flags"] and "2020-01" in report["flags"][0]
    archive, _ = gb.load_archive(tmp_path / "history", SEED)
    rec = archive.records[("kartli-gori", 2020, 1)]
    assert rec.energy == 7.91 and rec.pending_energy == 8.91  # displayed value unchanged
    sources = json.loads((tmp_path / "history" / "sources.json").read_text())
    assert len(sources["2020"]["history"]) == 1  # previous document hash retained


def test_layout_change_captcha_and_corrupt_documents_keep_existing_data(tmp_path):
    fake = FakeGSE({2020: text(2020).replace("ianvari", "January"), 2026: text(2026).replace("43,75", "53,75", 1)})
    fake.status[2025] = 403
    report = run(tmp_path, fake, T0)
    assert report["documents"]["2020"] == gb.UNSUPPORTED
    assert report["documents"]["2026"] == gb.INVALID
    assert report["documents"]["2025"] == gb.DOWNLOAD_FAILED  # 403 / CAPTCHA page is not a PDF
    archive, _ = gb.load_archive(tmp_path / "history", SEED)
    assert archive.records[("kartli-gori", 2020, 1)].verification_status == wh.OWNER
    assert ("ruisi", 2026, 10) not in archive.records


def test_document_removed_from_page_is_reported_missing_and_data_kept(tmp_path):
    fake = FakeGSE({2026: text(2026)})
    run(tmp_path, fake, T0)
    fake.page["data"]["contents"][0]["files"] = [f for f in fake.page["data"]["contents"][0]["files"] if f["name"] != "2026"]
    report = run(tmp_path, fake, T0 + timedelta(days=3))
    assert report["documents"]["2026"] == gb.MISSING
    archive, _ = gb.load_archive(tmp_path / "history", SEED)
    assert archive.records[("kartli-gori", 2026, 7)].verification_status == wh.VERIFIED


def test_monitor_never_fills_gaps():
    fake_months = gb.parse_balance_text(text(2016), 2016).stations["kartli-gori"]
    assert set(fake_months) == {10, 11, 12}  # January-September 2016 stay absent


def test_incomplete_archive_is_not_reseeded(tmp_path):
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "wind_monthly.csv").write_text("x")
    with pytest.raises(gb.StructureError):
        gb.load_archive(tmp_path / "history", SEED)


def test_workflow_is_owner_gated_and_separate_from_collector():
    wf = (HERE.parents[1] / ".github" / "workflows" / "history-monitor.yml").read_text(encoding="utf-8")
    assert "vars.HISTORY_MONITOR_ENABLED == 'true'" in wf  # schedule does nothing until enabled
    assert "history_monitor.py check" in wf and "collector.py" not in wf
    assert "group: collect-gse" in wf and "cancel-in-progress: false" in wf  # never push concurrently
    assert "pull_request" not in wf  # trusted default-branch code only
