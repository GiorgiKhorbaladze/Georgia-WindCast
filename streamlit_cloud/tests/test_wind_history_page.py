"""Issue #52 dashboard: calculations on the reviewed seed and the page in both languages (offline)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import page_text
from defusedxml import ElementTree
from streamlit.testing.v1 import AppTest

import wind_history as wh
import wind_history_view as v
from i18n import T, tr

APP = str(Path(__file__).resolve().parents[1] / "app.py")
SEED = v.SEED.read_text(encoding="utf-8")


def seed_records():
    return wh.public_records(wh.parse_records(SEED))


def df_of(records):
    return v.frame(records)


# --- calculations --------------------------------------------------------------------------
def test_kpis_from_seed_match_owner_figures():
    df = df_of(seed_records())
    assert v.ym(v.latest_period(df)) == (2026, 7)
    assert v.latest_complete_year(df) == 2025  # 2026 partial, 2016 Oct-Dec only
    yoy = v.ytd_yoy(df, 2026, 7)
    assert (round(yoy.current, 2), round(yoy.previous, 2)) == (68.27, 48.51)
    assert round(yoy.change_pct, 1) == 40.7
    assert yoy.existing == ["kartli-gori"] and round(yoy.existing_pct, 2) == -2.56  # like-for-like
    assert yoy.new_farms == ["zemo-wind"] and round(yoy.new_contribution, 2) == 21.0


def test_annual_totals_and_partial_years():
    ann = v.annual(df_of(seed_records()))
    k = ann[ann.station_id == "kartli-gori"].set_index("year")
    assert [round(k.gwh[y], 2) for y in range(2017, 2026)] == [87.74, 84.28, 84.70, 90.84, 83.36, 87.50, 86.11, 77.57, 79.41]
    assert not k.complete[2016] and not k.complete[2026] and k.complete[2025]
    assert round(k.gwh[2016], 2) == 9.02


def test_missing_months_stay_missing_and_cumulative_never_bridges_gaps():
    recs = [r for r in seed_records() if not (r.station_id == "kartli-gori" and (r.year, r.month) == (2024, 5))]
    df = df_of(recs)
    assert v.coverage(df)[0].gaps == [(2024, 5)]
    assert v.month_matrix(df).loc[2024].isna().tolist()[4]  # NaN, not 0
    cum = v.cumulative(df, 2024)
    assert cum[3] is not None and cum[4:] == [None] * 8  # stops at the gap
    assert not v.year_complete(df, 2024)
    assert v.cumulative(df_of(seed_records()), 2016)[:9] == [None] * 9  # before operation: empty
    assert v.cumulative(df_of(seed_records()), 2016)[11] == pytest.approx(9.02)


def test_zero_is_a_value_and_absent_is_not():
    df = df_of(seed_records())
    oct16 = df[(df.year == 2016) & (df.month == 10)]
    assert oct16.gwh.tolist() == [0.0]  # reported zero is kept
    assert df[(df.station_id == "zemo-wind") & (df.year < 2026)].empty  # placeholders were never imported


def test_monthly_yoy_separates_new_farms():
    t = v.monthly_yoy(df_of(seed_records()), 2026).set_index("month")
    assert t.loc[3, "new_farms"] == pytest.approx(3.95)
    assert t.loc[3, "existing_delta"] == pytest.approx(10.22 - 6.47)
    assert t.loc[8].isna().all() or t.loc[8, "current"] is None


def test_pending_values_never_reach_the_page():
    recs = wh.parse_records(SEED)
    pending = replace(recs[0], year=2026, month=8, verification_status=wh.PENDING)
    assert pending not in wh.public_records(recs + [pending])


def test_csv_and_xlsx_exports_carry_provenance():
    df = df_of(seed_records())
    csv = v.to_csv(df).decode("utf-8-sig").splitlines()
    assert csv[0].split(",") == v.EXPORT_COLUMNS and len(csv) == 124
    with zipfile.ZipFile(io.BytesIO(v.to_xlsx(df))) as z:
        sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
        ElementTree.fromstring(z.read("xl/workbook.xml"))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rows = sheet.findall(f"{ns}sheetData/{ns}row")
    assert len(rows) == 124
    texts = [t.text for t in rows[1].iter(f"{ns}t")]
    assert "ქართლის ქარის ელექტროსადგური" in texts and wh.OWNER in texts


def test_load_falls_back_to_seed_when_archive_absent_or_broken():
    with patch("wind_history_view.remote_csv", return_value=None):
        assert v.load("https://example.invalid/").origin == "seed"
    with patch("wind_history_view.remote_csv", return_value="garbage"):
        got = v.load("https://example.invalid/")
        assert got.origin == "seed" and got.error == "HistoryFormatError"
    archive = SEED.replace(wh.OWNER, wh.VERIFIED)
    with patch("wind_history_view.remote_csv", return_value=archive):
        got = v.load("https://example.invalid/")
        assert got.origin == "archive" and all(r.verification_status == wh.VERIFIED for r in got.records)


# --- page ----------------------------------------------------------------------------------
def run(lang="ka", archive=None):
    import streamlit as st

    st.cache_data.clear()  # the page caches the archive for hours; each test loads its own
    at = AppTest.from_file(APP, default_timeout=60)
    with patch("wind_history_view.remote_csv", return_value=archive):
        at.run()
        if lang == "en":
            at.sidebar.radio[0].set_value("English").run()
        at.sidebar.radio[1].set_value("wind_history").run()
    assert not at.exception, at.exception
    return at


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_page_renders_titles_kpis_and_honest_labels(lang):
    at = run(lang)
    text = page_text(at)
    assert tr("page_wind_history", lang) in text and tr("wh_subtitle", lang) in text
    assert "68.27" in text and "+40.7%" in text and "79.41" in text  # YTD, YoY, latest complete year
    assert "-2.6%" in text  # like-for-like change at existing farms is shown next to the headline
    assert tr("wh_energy_note", lang)[:30] in text  # GWh energy, not MW power
    captions = " ".join(c.value for c in at.caption)
    assert tr("wh_origin_seed", lang) in captions and tr("wh_legend", lang) in captions
    assert "0%" in text  # verification share: nothing is presented as official yet
    assert len(at.get("download_button")) == 2
    titles = [s.value for s in at.subheader]
    for key in ("wh_monthly", "wh_annual", "wh_heatmap", "wh_yoy", "wh_cumulative", "wh_table"):
        assert tr(key, lang) in titles


def test_page_reports_official_share_from_archive():
    archive = SEED.replace(wh.OWNER, wh.VERIFIED)
    at = run("en", archive)
    text = page_text(at)
    assert "100%" in text
    assert tr("wh_origin_archive", "en") in " ".join(c.value for c in at.caption)


def test_page_lists_months_without_data_for_partial_year():
    at = run("en")
    assert tr("wh_no_data_months", "en", months="Aug, Sep, Oct, Nov, Dec") in page_text(at)


def test_navigation_keeps_existing_pages_and_adds_history():
    at = run("ka")
    options = at.sidebar.radio[1].options
    assert options == [tr(f"page_{p}", "ka") for p in
                       ("overview", "system_map", "balance", "analytics", "wind_history", "forecast", "accuracy", "data")]


def test_texts_are_complete_and_follow_house_rules():
    keys = [k for k in T if k.startswith("wh_")] + ["page_wind_history"]
    assert len(keys) > 30
    for k in keys:
        assert T[k]["ka"] and T[k]["en"]
        assert "MW " not in T[k]["en"].replace("(MW)", "") or k == "wh_energy_note"
    assert T["page_wind_history"] == {"ka": "ქარის გენერაციის ისტორია", "en": "Wind Generation History"}
    assert T["page_analytics"]["ka"] == "ისტორიული ანალიზი"  # existing page kept
