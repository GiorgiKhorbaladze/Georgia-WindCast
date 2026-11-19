"""Georgian-first terminology and GSE quality codes (owner policy in Issue #18, 17.11.2026)."""

from __future__ import annotations

import json
from datetime import timedelta
import re
import pytest
from conftest import page_text

from i18n import T, tr

KA = " ".join(e["ka"] for e in T.values())
EN = " ".join(e["en"] for e in T.values())


def test_quality_codes_are_never_expanded_into_guessed_meanings():
    for guess in (r"ACT\W{0,3}(=|-|:)?\s*Actual", r"Actual\s*\(ACT\)", "Not refreshed", "Substitut", "Blocked", r"NRE\s*\(\w"):
        assert not re.search(guess, EN) and not re.search(guess, KA), guess
    assert "≠" not in KA + EN  # no symbol-only legend
    # Public UI names no quality codes (owner decision 19.11.2026); codes stay in data and docs.
    for code in ("ACT", "NRE", "SUB", "BLS"):
        assert not re.search(rf"\b{code}\b", KA + EN), code
    assert T["st_unverified"]["ka"] == "დაუდასტურებელი მონაცემი"  # neither "wrong" nor "confirmed"
    assert T["st_unverified"]["en"] == "Unconfirmed reading"


def test_generation_quartiles_are_not_called_windy_or_calm():
    for key in ("ren_cmp", "ren_windy", "ren_calm", "ren_top", "ren_bottom", "ren_cmp_sub"):
        assert "უქარო" not in T[key]["ka"] and "ქარიან" not in T[key]["ka"]
        assert not re.search(r"\b(windy|calm)\b", T[key]["en"], re.I)
    assert "გენერაცი" in T["ren_top"]["ka"] and "generation" in T["ren_top"]["en"]
    assert "არა ქარის სიჩქარის" in T["ren_cmp_how"]["ka"] and "not by wind speed" in T["ren_cmp_how"]["en"]


def test_freshness_is_not_presented_as_completeness_or_schedule_health():
    assert T["h_healthy"]["ka"] == "ბოლო შენახული მონაცემი 6 საათზე ახალია"
    assert "შენახულია" not in T["h_healthy"]["ka"] and "stored" not in T["h_healthy"]["en"].replace("stored data", "")
    assert "6 საათზე ძველია" in T["h_stale"]["ka"]
    assert "არ ადასტურებს" in T["h_age_note"]["ka"]


@pytest.mark.parametrize("key, ka, acr", [
    ("mae", "საშუალო აბსოლუტური ცდომილება", "(MAE)"),
    ("rmse", "საშუალო კვადრატული ცდომილების ფესვი", "(RMSE)"),
    ("bias", "სისტემატური ცდომილება", "(Bias)"),
    ("dir_mae", "მიმართულების საშუალო აბსოლუტური ცდომილება", "(MAE)"),
    ("ref_era5", "მეტეოროლოგიური ხელახალი ანალიზი", "(ERA5)"),
    ("persistence", "წინა მნიშვნელობის შენარჩუნება", "(persistence)"),
    ("climatology", "კლიმატოლოგია", "(climatology)"),
])
def test_acronyms_have_a_georgian_explanation_first(key, ka, acr):
    text = T[key]["ka"]
    assert text.index(ka) < text.index(acr)


def test_units_and_sources_are_explained_once():
    assert "მეგავატი (MW)" in T["units_note"]["ka"] and "მეგავატსაათი (MWh)" in T["units_note"]["ka"]
    assert "მეტრი წამში" in T["units_note"]["ka"]
    m = T["method_text"]["ka"]
    assert "საქართველოს სახელმწიფო ელექტროსისტემა“" in m and "კოორდინირებული უნივერსალური დროით (UTC)" in m
    assert "(SCADA)" in T["disclaimer"]["ka"]
    assert "წინსწრების დრო 6 სთ-ზე ნაკლები" in T["ref_analysis"]["ka"]  # lead time, not just issue time
    assert "კალიბრირებული სანდოობის ინტერვალი" in T["mw_band_note"]["ka"]
    assert "საბაზისო მეთოდზე უარესი" in T["mw_weak"]["ka"] and "(MAE)" in T["mw_weak"]["ka"]


def test_author_credit_and_map_texts_are_preserved():
    assert T["author_name"] == {"ka": "გიორგი ხორბალაძე", "en": "Giorgi Khorbaladze"}
    assert "საით მიემართება ქარი" in T["map_arrow_note"]["ka"]


# ------------------------------------------------------------------------- pages (AppTest)

def with_codes(rows, code="NRE", every=40):
    from dataclasses import replace
    return [replace(r, quality=code) if k % every == 0 else r for k, r in enumerate(rows)]


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_overview_chart_keeps_every_value_but_shows_no_codes(lang):
    import test_pages
    rows = with_codes(test_pages.durable_two_days())
    at = test_pages.run("overview", lang, rows)
    text = page_text(at)
    assert tr("units_note", lang) in text and "NRE" not in text
    charts = [json.loads(c.proto.spec) for c in at.get("plotly_chart")]
    assert not any("NRE" in json.dumps(c) or "ACT" in json.dumps(c) for c in charts)  # legend and tooltips
    gen = next(c for c in charts if c["data"][0].get("name") == tr("series_mw", lang))
    assert len(gen["data"]) == 1  # one series: non-ACT values are neither dropped nor drawn separately
    ys = [v for v in _values(gen["data"][0]["y"]) if v == v]
    now = test_pages.NOW  # chart window: the last 24 h before the page's clock
    assert len(ys) == sum(1 for r in rows if now - timedelta(hours=24) <= r.period_label_utc <= now)
    assert all('"MW"' != c["layout"].get("yaxis", {}).get("title", {}).get("text") for c in charts)


def test_peak_card_shows_value_and_time_without_code():
    import test_pages
    rows = test_pages.durable_two_days()
    from dataclasses import replace
    rows = rows[:-1] + [replace(rows[-1], value_mw=99.0, quality="NRE")]
    text = page_text(test_pages.run("overview", "ka", rows))
    assert "99.0" in text and "NRE" not in text and "3-წუთიანი საშუალო" in text


def _values(arr):
    """Plotly JSON arrays may be binary-encoded ({"dtype", "bdata"})."""
    if isinstance(arr, dict):
        import base64
        import numpy as np
        return list(np.frombuffer(base64.b64decode(arr["bdata"]), dtype=arr["dtype"]).astype(float))
    return [float("nan") if v is None else v for v in arr]


def test_gaps_are_not_bridged_in_overview_charts():
    import test_pages
    rows = test_pages.durable_two_days(skip_yesterday=0)
    rows = [r for r in rows if not (rows[-1].period_label_utc - timedelta(hours=9) < r.period_label_utc < rows[-1].period_label_utc - timedelta(hours=2))]
    at = test_pages.run("overview", "ka", rows)
    charts = [json.loads(c.proto.spec) for c in at.get("plotly_chart")]
    profile = next(c for c in charts if len(c["data"]) == 3 and c["data"][0].get("mode") == "lines+markers")
    today = _values(profile["data"][-1]["y"])
    assert len(today) == 24 and any(v != v for v in today)  # missing hours are NaN gaps, not skipped
    gen = next(c for c in charts if c["data"][0].get("name") == tr("series_mw", "ka"))
    assert gen["data"][0].get("fill") in (None, "none") and gen["data"][0]["connectgaps"] is False


def test_backfill_counter_wording_matches_the_collector():
    # collector.RunReport.backfilled = inserted periods older than 1 h (a subset of "inserted")
    assert "ერთ საათზე ძველი" in T["h_backfill"]["ka"] and "older than 1 h" in T["h_backfill"]["en"]
    assert "საბაზისო მეთოდისა („{b}“)" in T["mw_weak"]["ka"]


def test_georgian_texts_use_the_full_name_instead_of_gse():
    # owner decision 17.11.2026: no "GSE" abbreviation in the Georgian interface
    assert [k for k, v in T.items() if "GSE" in v["ka"]] == []
    assert T["gse_tag"]["ka"] == "საქართველოს სახელმწიფო ელექტროსისტემა" and T["gse_tag"]["en"] == "GSE"


def test_overview_in_georgian_shows_no_gse_abbreviation():
    import test_pages
    at = test_pages.run("overview", "ka", test_pages.durable_two_days())
    text = page_text(at)
    assert "საქართველოს სახელმწიფო ელექტროსისტემა" in text
    visible = re.sub(r"<[^>]+>", " ", text)  # ignore markup and URLs in attributes
    assert "GSE" not in visible


# --------------------------------------- public UI without quality codes (owner request 19.11.2026)

@pytest.mark.parametrize("lang", ["ka", "en"])
def test_analytics_has_no_code_filter_or_act_checkbox_and_counts_every_value(lang):
    import test_pages
    rows = with_codes(test_pages.durable_two_days(), every=7)  # many non-ACT periods
    at = test_pages.run("analytics", lang, rows)
    assert len(at.multiselect) == 0  # former quality-code filter
    assert not any("ACT" in c.label for c in at.checkbox)  # former "ACT only" ramp option
    text = page_text(at)
    assert not re.search(r"\b(ACT|NRE)\b", text)
    # same totals as with all codes ACT: hiding the codes neither drops nor changes values
    plain = page_text(test_pages.run("analytics", lang, test_pages.durable_two_days()))
    num = re.compile(r"\d[\d\s]*[.,]?\d*\s*MWh")
    assert num.findall(text)[:3] == num.findall(plain)[:3]


def test_quality_information_is_kept_internally():
    import analytics as an
    import ramps as rp
    import test_pages
    rows = with_codes(test_pages.durable_two_days(), every=7)
    df = an.frame([dict(time=r.period_label_utc, value_mw=r.value_mw, quality=r.quality) for r in rows])
    assert set(df["quality"]) == {"ACT", "NRE"}  # stored codes untouched
    h = rp.HORIZONS["15min"]
    assert len(rp.deltas(df, h, act_only=True)) < len(rp.deltas(df, h))  # sensitivity option still works internally
