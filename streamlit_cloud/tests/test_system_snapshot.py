"""Tests for the map data contract, same-period arithmetic and tie-line evidence."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from balance import BLOCKS, inspect_interchange, parse_balance
from app.ingestion.gse_parser import parse_wind_export
from store import BalanceRecord
from system_snapshot import period_payload, snapshot_badge
from test_pages import NOW, run

LABEL = NOW - timedelta(minutes=1)
ROW = BalanceRecord(
    LABEL, "16.11.2026 20:09:00", 100.0, 20.0, -1.0, 0.0, 119.0, 130.0,
    ";".join(f"{block}:ACT" for block in BLOCKS), NOW, "recorded-digest", "gse-balance-03m/2", 13.0, 2.0,
)
FIXTURES = Path(__file__).resolve().parents[2] / "backend/tests/fixtures/gse"


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_streamlit_passes_coherent_periods_to_component(lang):
    older = replace(ROW, period_label_utc=LABEL - timedelta(minutes=3), generation_mw=999.0)
    with patch("history.HistoryReader.balance", return_value=[older, ROW]), patch("system_snapshot.MAP") as mount:
        run("system_map", lang)
    props = mount.call_args.kwargs
    assert props["lang"] == lang
    first, current = props["periods"]
    assert current["values"]["generation"] == 119 and first["values"]["generation"] == 999
    assert current["values"]["solar"] == 0 and current["values"]["wind"] == -1
    assert current["residual"] == 0 and first["residual"] == 880
    assert current["label"] == ROW.period_label_local
    assert "ACT" not in str(props) and ROW.payload_sha256 not in str(props)


def test_missing_and_stale_data():
    old = replace(ROW, period_label_utc=LABEL - timedelta(hours=1), import_mw=None, export_mw=float("nan"))
    period, = period_payload([old], NOW, False)
    assert period["status"] == "stale" and period["residual"] is None
    assert period["values"]["import"] is None and period["values"]["export"] is None
    assert snapshot_badge(ROW, NOW, True) == "unconfirmed"
    assert snapshot_badge(None, NOW, False) == "unavailable"


def test_recent_period_with_provisional_quality():
    provisional = replace(ROW, quality=ROW.quality.replace("wind:ACT", "wind:NRE"))
    period, = period_payload([provisional], NOW, False)
    assert period["status"] == "unconfirmed" and not period["wind_confirmed"]
    assert period["values"]["wind"] == -1


@pytest.mark.parametrize("file", sorted(FIXTURES.glob("real_*.xml")), ids=lambda path: path.name)
def test_signed_line_and_subtotal_reconcile_with_collector(file):
    body = file.read_bytes()
    label, ties = inspect_interchange(body)
    same_label, balance = parse_balance(body)
    wind = parse_wind_export(body)
    assert label == same_label == wind.period_label_utc
    assert balance.wind == wind.value_mw
    expected = {
        "real_act_15112026_0009.xml": (1075.829346, 313.713287, 73.599297, 0, 1463.141968, 1536.535400,
                                     73.393583, 0),
        "real_nre_15112026_0003.xml": (1171.450562, 313.832825, 91.333824, 0, 1583.024292, 1597.384644,
                                     32.746205, 30.897966),
    }
    assert tuple(getattr(balance, field) for field in (*BLOCKS, "imports", "exports")) == pytest.approx(
        expected[file.name], abs=1e-8, rel=0
    )
    identifiers = [(row.block, row.identifier, row.is_subtotal) for row in ties]
    assert all(row.identifier for row in ties) and len(identifiers) == len(set(identifiers))
    russia = [row for row in ties if "RUSSIA" in row.block]
    assert {row.identifier for row in russia if not row.is_subtotal} == {"Salkhino", "Java", "Nakaduli"}
    subtotal, = (row for row in russia if row.is_subtotal)
    assert subtotal.mw == 0
    assert sum(row.mw for row in russia if not row.is_subtotal) > 32
    assert len([row for row in ties if not row.is_subtotal]) == 3
    assert any(row.identifier == "Java" and row.quality == "BLS" for row in russia)
    line_blocks = {row.block for row in ties if not row.is_subtotal}
    signed = [row.mw for row in ties if not row.is_subtotal or row.block not in line_blocks]
    assert sum(max(value, 0) for value in signed) == pytest.approx(balance.imports)
    assert sum(max(-value, 0) for value in signed) == pytest.approx(balance.exports)
    residual = balance.imports - balance.exports - balance.net_interchange
    if "nre" in file.name:
        assert residual == pytest.approx(-12.512113)
    else:
        assert residual == pytest.approx(0, abs=.01)


def test_audited_1712_period_preserves_all_eight_values_and_signed_difference():
    # Archived aggregate row from data commit ae1fe3f, 20 November 2026 17:12 Tbilisi.
    label = LABEL.replace(day=20, hour=13, minute=12)
    row = replace(
        ROW, period_label_utc=label, period_label_local="20.11.2026 17:12:00",
        retrieved_at_utc=label + timedelta(minutes=3, seconds=34),
        hydro_mw=1602.259766, thermal_mw=424.108429, wind_mw=-0.071, solar_mw=8.629999,
        generation_mw=2034.683594, consumption_mw=2025.301025, import_mw=18.299999,
        export_mw=10.714442, quality="hydro:NRE;thermal:SUB;wind:ACT;solar:SUB;generation:NRE;consumption:NRE",
    )
    period, = period_payload([row], label + timedelta(minutes=4), False)
    assert period["label"] == "20.11.2026 17:12:00"
    assert period["retrieved"] == "20.11.2026 17:15:34"
    assert period["status"] == "unconfirmed" and period["wind_confirmed"]
    assert period["values"] == {
        name: getattr(row, f"{name}_mw") for name in (*BLOCKS, "import", "export")
    }
    assert period["residual"] == pytest.approx(16.968126)
    assert row.hydro_mw + row.thermal_mw + row.wind_mw + row.solar_mw - row.generation_mw == pytest.approx(.243600)


def test_line_level_panels_are_gated_off_in_production():
    # Issue #49 / contract v1: production sends no cross-border document; the frontend renders
    # per-block records only for a same-period document with publication == "authorized".
    import system_snapshot
    assert system_snapshot.CROSS_BORDER_ENABLED is False
    with patch("history.HistoryReader.balance", return_value=[ROW]), patch("system_snapshot.MAP") as mount:
        run("system_map", "en")
    assert mount.call_args.kwargs["cross_border"] is None
    js = (Path(system_snapshot.__file__).parent / "system_map_frontend/map.js").read_text("utf-8")
    assert 'doc.publication !== "authorized"' in js and 'doc.contract !== "cross_border_flow/v1"' in js
    assert "docTime === period.time" in js  # never a document from another period
    assert "<path" not in js.split("function crossBorder")[1].split("function linkHighlight")[0]  # no routes drawn
