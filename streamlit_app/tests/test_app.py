"""Renders the whole Streamlit page offline (recorded payloads) with Streamlit's AppTest."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import META, GseServer, weather_handler
from windcast_demo import core

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch, gse: GseServer) -> GseServer:
    monkeypatch.setattr(core, "gse_client", lambda ua=None, timeout=10.0: gse.client())
    monkeypatch.setattr(
        core,
        "weather_client",
        lambda ua=None: httpx.Client(transport=httpx.MockTransport(weather_handler([META]))),
    )
    st.cache_data.clear()
    st.cache_resource.clear()
    return gse


def _run(lang: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    if lang:
        at.sidebar.radio[0].set_value(lang).run()
    return at


def test_page_renders_georgian_with_data_and_disclaimers(offline: GseServer) -> None:
    at = _run()
    assert not at.exception
    assert at.title[0].value == "Georgia WindCast"
    assert "საჩვენებელი ვერსია" in at.info[0].value
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["ბოლო 3-წუთიანი საშუალო"].endswith("MW")
    text = " ".join(m.value for m in at.markdown)
    assert "აქტუალური" in text  # freshness badge from the source label
    assert offline.requests  # data came through the GSE client


def test_page_renders_english_and_forecast_controls(offline: GseServer) -> None:
    at = _run("en")
    assert not at.exception
    assert "Demo edition" in at.info[0].value
    assert [s.label for s in at.selectbox] == ["Site", "Height"]
    assert at.selectbox[1].value == 120


def test_upstream_outage_shows_generic_warning(
    offline: GseServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    offline.override = lambda name: httpx.Response(503, headers={"content-type": "text/html"})

    def broken(ua=None):
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))

    monkeypatch.setattr(core, "weather_client", broken)
    at = _run("en")
    assert not at.exception
    warnings = " ".join(w.value for w in at.warning)
    assert "upstream_unavailable" in warnings
    assert "Forecast temporarily unavailable" in warnings
    assert "503" not in warnings and "500" not in warnings
