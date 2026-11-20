"""Tests for the map data contract, same-period arithmetic and tie-line evidence."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from balance import BLOCKS, inspect_interchange, parse_balance
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
    assert label == same_label
    russia = [row for row in ties if "RUSSIA" in row.block]
    assert {row.identifier for row in russia if not row.is_subtotal} == {"Salkhino", "Java", "Nakaduli"}
    assert any(row.is_subtotal for row in russia)
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
