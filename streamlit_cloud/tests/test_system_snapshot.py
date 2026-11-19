"""Offline navigation and data integrity checks for the system snapshot."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest

from conftest import page_text
from i18n import tr
from store import BalanceRecord
from test_pages import NOW, run

LABEL = NOW - timedelta(minutes=1)
ROW = BalanceRecord(
    LABEL, "16.11.2026 20:09:00", 100.0, 20.0, -1.0, 0.0, 119.0, 130.0,
    "wind:ACT;hydro:SUB", NOW, "recorded-digest", "gse-balance-03m/2", 13.0, 2.0,
)


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_snapshot_from_one_period_in_both_languages(lang):
    older = replace(ROW, period_label_utc=LABEL - timedelta(minutes=3), hydro_mw=999.0)
    with patch("history.HistoryReader.balance", return_value=[older, ROW]):
        app = run("system_map", lang)
    text = page_text(app)
    for key in ("snapshot_title", "snapshot_recent", "snapshot_frequency", "st_unavailable"):
        assert tr(key, lang) in text
    assert app.subheader[0].value == tr("snapshot_map_title", lang)
    assert any("16.11.2026 20:09:00" in item.value for item in app.caption)
    for value in ("100.00", "-1.00", "0.00", "13.00", "2.00"):
        assert f">{value}<" in text
    assert "999.00" not in text
    spec = app.get("deck_gl_json_chart")[0].proto.json
    assert "ScatterplotLayer" in spec and "LineLayer" not in spec


def test_stale_legacy_period_has_no_inferred_gross_flows():
    legacy = replace(ROW, period_label_utc=LABEL - timedelta(hours=1), import_mw=None, export_mw=None)
    with patch("history.HistoryReader.balance", return_value=[legacy]):
        app = run("system_map", "en")
    text = page_text(app)
    assert tr("st_stale", "en") in text
    assert any(tr("snapshot_flow_note", "en") in item.value for item in app.caption)
    assert ">13.00<" not in text and ">2.00<" not in text and ">11.00<" not in text


def test_missing_data_leaves_map_available():
    with patch("history.HistoryReader.balance", return_value=[]):
        app = run("system_map", "en")
    assert tr("snapshot_empty", "en") in " ".join(i.value for i in app.info)
    assert app.get("deck_gl_json_chart")
