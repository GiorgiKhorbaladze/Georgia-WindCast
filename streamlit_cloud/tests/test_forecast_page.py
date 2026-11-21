"""Issue #57 forecast page: renders from the forecast-data outputs; never shows forecast values
while PUBLISH_FORECAST is False. Fixtures are trimmed outputs of a real local backtest."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import page_text
from streamlit.testing.v1 import AppTest

from i18n import T, tr

APP = str(Path(__file__).resolve().parents[1] / "app.py")
FIX = Path(__file__).resolve().parent / "fixtures" / "forecast"


def fake_fetch(path, base=None):
    name = path.split("/")[-1]
    if name == "day_ahead_summary_live.json":
        return '{"models": []}\n'  # what publish writes before the first complete day
    f = FIX / name
    return f.read_text(encoding="utf-8") if f.exists() else None


def run(lang="ka", fetch=fake_fetch, cadence=None):
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=60)
    with patch("forecast_page.fetch", side_effect=fetch) as mocked:
        at.run()
        if lang == "en":
            at.sidebar.radio[0].set_value("English").run()
        at.sidebar.radio[1].set_value("gen_forecast").run()
        if cadence:
            at.radio(key="fc_cad").set_value(cadence).run()
        calls = [c.args[0] for c in mocked.call_args_list]
    assert not at.exception, at.exception
    return at, calls


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_page_shows_scores_but_never_forecast_values(lang):
    at, calls = run(lang)
    text = page_text(at)
    assert tr("page_gen_forecast", lang) in text and tr("fc_experimental", lang) in text
    assert tr("fc_withheld", lang) in text
    assert "evaluation/latest.csv" not in calls  # forecast values are not even downloaded
    assert not any("ledger" in c or "day_ahead_live" in c or "tournament_" in c for c in calls)
    assert any(w.value == tr("fc_insufficient", lang, days=14, cases=200) for w in at.warning)
    assert len(at.dataframe) == 2 and len(at.get("download_button")) == 1
    assert not any(w.value == tr("fc_load_error", lang) for w in at.warning)  # empty CSVs are fine


def test_empty_archive_is_explained():
    at, _ = run("en", fetch=lambda p, base=None: None)
    assert any(i.value == tr("fc_no_data", "en") for i in at.info)


@pytest.mark.parametrize("cadence, key", [("1mo", "fc_monthly_note"), ("1d", "fc_day_none")])
def test_monthly_and_daily_views_are_honest(cadence, key):
    at, _ = run("en", cadence=cadence)
    assert any(i.value == tr(key, "en") for i in at.info)


def test_navigation_and_texts():
    assert T["page_gen_forecast"] == {"ka": "ქარის გენერაციის პროგნოზი", "en": "Wind Generation Forecast"}
    for k, v in T.items():
        if k.startswith("fc_"):
            assert "GSE" not in v["ka"] and "—" not in v["ka"] + v["en"], k


def test_tournament_table_counts_independent_days():
    at, _ = run("en")
    assert tr("fc_tour", "en") in [s.value for s in at.subheader]
    assert len(at.dataframe) == 2  # stage I comparison + tournament
    cols = list(at.dataframe[1].value.columns)
    assert tr("fc_col_indep", "en") in cols
    assert any(tr("fc_tour_noweather", "en") == c.value for c in at.caption)
