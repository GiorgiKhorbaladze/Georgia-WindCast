"""Cross-border exchange data model (contract v1): strict parse, reconciliation, persistence, gate."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from app.ingestion.gse_parser import GseSchemaError, GseValueError

import interchange as ix
from balance import parse_balance

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend/tests/fixtures/gse"
ACT = (FIXTURES / "real_act_15112026_0009.xml").read_bytes()
NRE = (FIXTURES / "real_nre_15112026_0003.xml").read_bytes()


@pytest.mark.parametrize("body", [ACT, NRE], ids=["act", "nre"])
def test_records_ids_and_blocks_as_published(body):
    s = ix.parse_interchange(body)
    assert [b.block_country_label for b in s.blocks] == ["AZERBAIJAN", "ARMENIA", "RUSSIA", "TURKEY"]
    ids = [r.source_id for r in s.records]
    assert len(ids) == len(set(ids)) == 7
    assert {r.identifier for r in s.records if r.kind == "line"} == {"Salkhino", "Java", "Nakaduli"}
    assert all(r.block_country_label == "RUSSIA" for r in s.records if r.kind == "line")  # lines only there
    assert [b.lines_published for b in s.blocks] == [False, False, True, False]
    assert s.payload_sha256 and len(s.payload_sha256) == 64


def test_sign_direction_and_negative_zero():
    s = ix.parse_interchange(NRE)
    az = next(r for r in s.records if r.source_id == "AZERBAIJAN/subtotal/Azerbaij")
    assert az.mw == pytest.approx(-30.897966) and az.direction == "export"
    salkhino = next(r for r in s.records if r.identifier == "Salkhino")
    assert salkhino.mw == 0.0 and str(salkhino.mw) == "0.0" and salkhino.direction == "zero"  # "-0.000000"
    java = next(r for r in s.records if r.identifier == "Java")
    assert java.direction == "import" and java.quality == "BLS"  # raw code kept, not interpreted


@pytest.mark.parametrize("body", [ACT, NRE], ids=["act", "nre"])
def test_reconciles_with_archived_balance_and_closure(body):
    s = ix.parse_interchange(body)
    _, bal = parse_balance(body)
    # same lines-else-subtotal rule as the archive: identical gross flows
    assert s.gross_import_mw == pytest.approx(bal.imports, abs=1e-9)
    assert s.gross_export_mw == pytest.approx(bal.exports, abs=1e-9)
    assert s.net_from_balance_mw == pytest.approx(bal.consumption - bal.generation)
    # ACT file closes to rounding; the NRE file (generation/consumption coded NRE) leaves a published
    # arithmetic difference of 12.51 MW, which is reported as-is (never forced to zero).
    expected = 0.0 if body is ACT else 12.512113
    assert s.residual_mw == pytest.approx(expected, abs=0.01)
    russia = next(b for b in s.blocks if b.block_country_label == "RUSSIA")
    assert russia.subtotal.mw == 0 and russia.flow_mw > 32
    assert russia.subtotal_minus_lines == pytest.approx(-russia.flow_mw)  # subtotal never assumed = lines


def test_residual_is_reported_not_hidden():
    body = NRE.replace(b"VALUE='1597.384644'", b"VALUE='1617.384644'")  # consumption +20 MW (test-only)
    base = ix.parse_interchange(NRE).residual_mw
    s = ix.parse_interchange(body)
    assert s.residual_mw - base == pytest.approx(20.0, abs=0.01)
    assert ix.to_contract(s)["national"]["residual_mw"] == pytest.approx(base + 20.0, abs=0.01)


@pytest.mark.parametrize("mutation, error", [
    ((b"B2='Intercha' B3='Java'", b"B2='Interchx' B3='Java'"), GseSchemaError),  # unknown kind
    ((b"B3='Nakaduli'", b"B3='Java'"), GseSchemaError),  # duplicate source_id
    ((b"B2='IntchSum' B3='Turkey'", b"B2='Intercha' B3='Turkey'"), GseSchemaError),  # block w/o subtotal
    ((b"B3='Java' EL='P' IN='MvAvr03m' VALUE='18.299999'", b"B3='Java' EL='P' IN='MvAvr03m' VALUE='nan'"), GseValueError),
    ((b"B3='Java' EL='P' IN='MvAvr03m' VALUE='18.299999'", b"B3='Java' EL='P' IN='MvAvr03m' VALUE='99999'"), GseValueError),
    ((b"B3='Java' EL='P' IN='MvAvr03m'", b"B3='Java' EL='Q' IN='MvAvr03m'"), GseSchemaError),  # other quantity
    ((b"B3='Java'", b"B3=' '"), GseSchemaError),  # empty identifier
])
def test_strict_parse_refuses_surprises(mutation, error):
    old, new = mutation
    assert old in ACT
    with pytest.raises(error):
        ix.parse_interchange(ACT.replace(old, new, 1))


def test_hostile_xml_is_refused():
    with pytest.raises(GseSchemaError):
        ix.parse_interchange(b"<!DOCTYPE x [<!ENTITY a 'b'>]><GSE>&a;</GSE>")


def _series(n, java_value=b"18.299999", vary_nakaduli=True):
    """n consecutive 3-minute relabelled copies of a real file (test-only series)."""
    base = ix.parse_interchange(ACT).period_label_utc
    out = []
    for k in range(n):
        t = (base + timedelta(minutes=3 * k)).astimezone(ix.parse_interchange(ACT).period_label_utc.tzinfo)
        from zoneinfo import ZoneInfo
        local = t.astimezone(ZoneInfo("Asia/Tbilisi")).strftime("%d.%m.%Y %H:%M:%S")
        body = ACT.replace(b"Time='15.11.2026 00:09:00'", f"Time='{local}'".encode(), 1)
        body = body.replace(b"VALUE='18.299999'", b"VALUE='" + java_value + b"'", 1)
        if vary_nakaduli:
            body = body.replace(b"VALUE='14.300695'", f"VALUE='{14.300695 + k:.6f}'".encode(), 1)
        out.append(ix.parse_interchange(body))
    return out


def test_persistent_value_is_flagged_but_zero_and_varying_are_not():
    flags = ix.persistence_flags(_series(20))
    assert flags["RUSSIA/line/Java"] is True  # identical non-zero for one hour
    assert flags["RUSSIA/line/Nakaduli"] is False  # varies
    assert flags["RUSSIA/line/Salkhino"] is False  # zero is a legitimate idle reading
    assert flags["AZERBAIJAN/subtotal/Azerbaij"] is True  # unchanged in this synthetic copy series
    assert ix.persistence_flags(_series(19))["RUSSIA/line/Java"] is False  # below one hour


def test_contract_document_shape_and_gate():
    s = ix.parse_interchange(NRE)
    doc = ix.to_contract(s, persistent={"RUSSIA/line/Java"})
    json.dumps(doc)  # serialisable
    assert doc["contract"] == "cross_border_flow/v1" and doc["sign_convention"] == "positive_into_georgia"
    assert doc["period"] == {"label_utc": s.period_label_utc.isoformat(), "label_local": s.period_label_local,
                             "interval_minutes": 3, "label_marks": "interval_end"}
    assert doc["geometry"] is None and doc["publication"] == "not_authorized"
    russia = next(b for b in doc["blocks"] if b["block_country_label"] == "RUSSIA")
    java = next(r for r in russia["lines"] if r["identifier"] == "Java")
    assert java["availability"] == "persistent_value"
    az = next(b for b in doc["blocks"] if b["block_country_label"] == "AZERBAIJAN")
    assert az["lines"] == [] and az["lines_published"] is False  # no invented lines
    assert doc["national"]["gross_export_mw"] == pytest.approx(30.897966)


def test_not_wired_into_collector_archive_or_app():
    """Publication gate: until source rights and owner go-ahead, nothing imports this module."""
    sc = ROOT / "streamlit_cloud"
    for name in ("collector.py", "store.py", "history.py", "app.py", "system_snapshot.py", "data.py"):
        text = (sc / name).read_text("utf-8")
        assert "import interchange" not in text and "from interchange" not in text, name


def test_line_records_match_gse_published_line_list_and_coverage_is_explicit():
    s = ix.parse_interchange(ACT)
    lines = [r for r in s.records if r.kind == "line"]
    assert [ix.registry_entry(r) for r in lines] == [
        {"line_title": "Salkhino", "country": "RU", "voltage_kv": 220},
        {"line_title": "Java", "country": "RU", "voltage_kv": 110},
        {"line_title": "Nakaduli", "country": "RU", "voltage_kv": 110},
    ]
    assert all(ix.registry_entry(r) is None for r in s.records if r.kind == "subtotal")  # subtotal is no line
    cov = ix.line_coverage(s)
    assert cov["RU"]["not_individually_reported"] == ["Kavkasioni"]  # 500 kV line has no record in the file
    assert cov["AZ"]["individually_reported"] == [] and len(cov["AZ"]["published_lines"]) == 3
    assert cov["TR"]["published_lines"] == ["Adjara", "Meskheti"] and cov["AM"]["published_lines"] == ["Alaverdi"]
    doc = ix.to_contract(s)
    assert doc["line_coverage"] == cov and "retrieved 2026-11-20" in doc["line_registry_source"]


def test_registry_never_maps_on_country_mismatch_or_unknown_name():
    body = ACT.replace(b"B3='Nakaduli'", b"B3='Unknownline'")
    s = ix.parse_interchange(body)
    unknown = next(r for r in s.records if r.identifier == "Unknownline")
    assert ix.registry_entry(unknown) is None
    moved = ix.TieRecord("TURKEY/line/Java", "TOTAL TURKEY TIE LINES", "TURKEY", "line", "Java", 1.0, "ACT")
    assert ix.registry_entry(moved) is None  # published country RU != block TR
