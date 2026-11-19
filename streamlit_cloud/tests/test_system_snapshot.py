"""Offline navigation and data integrity checks for the system snapshot."""

import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest

from balance import BLOCKS

from conftest import page_text
from i18n import tr
from store import BalanceRecord
from test_pages import NOW, run

LABEL = NOW - timedelta(minutes=1)
ROW = BalanceRecord(
    LABEL, "16.11.2026 20:09:00", 100.0, 20.0, -1.0, 0.0, 119.0, 130.0,
    ";".join(f"{block}:ACT" for block in BLOCKS), NOW, "recorded-digest", "gse-balance-03m/2", 13.0, 2.0,
)


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_snapshot_from_one_period_in_both_languages(lang):
    older = replace(ROW, period_label_utc=LABEL - timedelta(minutes=3), hydro_mw=999.0)
    with patch("history.HistoryReader.balance", return_value=[older, ROW]):
        app = run("system_map", lang)
    text = page_text(app)
    for key in ("snapshot_title", "snapshot_recent", "snapshot_mix"):
        assert tr(key, lang) in text
    assert app.subheader[0].value == tr("snapshot_map_title", lang)
    assert any("16.11.2026 20:09:00" in item.value for item in app.caption)
    for value in ("100.00", "-1.00", "0.00", "13.00", "2.00"):
        assert f">{value}<" in text
    assert "999.00" not in text
    spec = map_spec(app)
    assert {layer["id"] for layer in spec["layers"]} == {
        "country-outline", "reference-cities", "verified-wind-sites",
    }
    cities = next(layer for layer in spec["layers"] if layer["id"] == "reference-cities")
    assert set("".join(city["name"] for city in cities["data"])) == set(cities["characterSet"])
    assert "System frequency" not in text and "ACT" not in text
    with patch("history.HistoryReader.balance", return_value=[older, ROW]):
        balance = page_text(run("balance", lang))
    assert ">13.00<" in balance and ">2.00<" in balance
    assert ">119<" in balance and ">130<" in balance


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


def map_spec(app):
    return json.loads(app.get("deck_gl_json_chart")[0].proto.json)


def test_map_controls_filter_layers_and_focus_verified_site():
    from data import SITES

    app = run("system_map", "en")
    app.selectbox(key="snapshot-focus").set_value(SITES[0].id).run()
    view = map_spec(app)["initialViewState"]
    assert (view["latitude"], view["longitude"]) == (SITES[0].latitude, SITES[0].longitude)
    assert view["zoom"] > 5.1
    assert any("uncertainty" in item.value for item in app.caption)
    for key in ("snapshot-border", "snapshot-places", "snapshot-wind"):
        app.checkbox(key=key).uncheck().run()
    assert map_spec(app)["layers"] == []


def test_recent_provisional_period_and_failed_refresh_are_not_reported_as_confirmed():
    from system_snapshot import snapshot_badge

    provisional = replace(ROW, quality=ROW.quality.replace("hydro:ACT", "hydro:SUB"))
    with patch("history.HistoryReader.balance", return_value=[provisional]):
        text = page_text(run("system_map", "en"))
    assert tr("snapshot_uncertain", "en") in text
    assert tr("snapshot_recent", "en") not in text and "SUB" not in text
    assert snapshot_badge(ROW, NOW, True)[1] == "unverified"
