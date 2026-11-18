"""Map wind arrows, per-site wind text and the Georgian/English text audit (Issue #18, 17.11.2026)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.ingestion.openmeteo import FORECAST, HourValue, parse_response
from conftest import page_text
from test_adapter import FORECAST_BODY

import compass
import sitemap
from data import SITES
from i18n import T, tr

VALID = datetime(2026, 11, 17, 7, 0, tzinfo=UTC)  # 11:00 Tbilisi


# --------------------------------------------------------------------------- arrow orientation

@pytest.mark.parametrize("frm, to, towards_en", [
    (0, 180, "towards south"),
    (45, 225, "towards south-west"),
    (90, 270, "towards west"),
    (180, 0, "towards north"),
    (270, 90, "towards east"),
    (359, 179, "towards south"),
    (360, 180, "towards south"),
])
def test_arrow_points_where_the_air_goes(frm, to, towards_en):
    assert compass.to_bearing(frm) == pytest.approx(to)
    assert compass.towards(to, "en") == towards_en
    # deck.gl turns icons counter-clockwise; the icon points north at angle 0
    assert sitemap.icon_angle(to) == pytest.approx((360 - to) % 360)


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_missing_direction_has_no_bearing(missing):
    assert compass.to_bearing(missing) is None
    assert compass.towards(missing, "ka") is None


def test_icon_is_inline_svg_pointing_up_with_tail_at_the_site():
    icon = sitemap.icon("wind")
    assert icon["url"].startswith("data:image/svg+xml;base64,")  # no external asset to go missing
    assert icon["anchorY"] == icon["height"]  # bottom centre = the site
    assert sitemap.icon("calm")["url"] != icon["url"]  # light wind is drawn differently


# --------------------------------------------------------------------------- per-site record

@pytest.mark.parametrize("lang", ["ka", "en"])
def test_site_record_text_and_arrow(lang):
    rec = sitemap.site_record(1, SITES[0], HourValue(VALID, 8.94, 102.0), lang)
    assert rec["has_arrow"] and not rec["calm"]
    assert rec["speed_txt"] == f"8.9 {tr('ms', lang)}"
    assert rec["dir_txt"] == ("102° - აღმოსავლეთიდან" if lang == "ka" else "102° - from east")
    assert rec["meta"] == tr("map_meta", lang, h=80, t="17.11 11:00")  # height and Tbilisi valid time
    assert rec["angle"] == pytest.approx(360 - 282)
    assert ("დასავლეთისკენ" if lang == "ka" else "towards west") in rec["tip"]
    assert (SITES[0].name_ka if lang == "ka" else SITES[0].name_en) in rec["tip"]


def test_light_wind_is_muted_and_explained():
    rec = sitemap.site_record(2, SITES[1], HourValue(VALID, 1.2, 200.0), "ka")
    assert rec["has_arrow"] and rec["calm"]
    assert rec["icon"] == sitemap.icon("calm")
    assert tr("calm_hint_map", "ka") in rec["tip"]


@pytest.mark.parametrize("value", [None, HourValue(VALID, None, 90.0), HourValue(VALID, 6.0, None)])
def test_missing_value_gets_no_arrow_and_says_so(value):
    rec = sitemap.site_record(3, SITES[2], value, "ka")
    assert not rec["has_arrow"] and rec["icon"] is None
    assert rec["dir_txt"] == tr("map_na", "ka") and rec["speed_txt"] == "-"
    json.dumps(rec)  # no NaN or objects that the map JSON cannot carry


# --------------------------------------------------------------------------- page (AppTest)

@pytest.fixture
def snapshot_at(monkeypatch):
    import test_pages
    series = parse_response(FORECAST_BODY, 3, FORECAST.heights)
    first = series[0].by_height[80][0].valid_at
    now = first + timedelta(hours=1, minutes=10)
    monkeypatch.setattr(test_pages, "NOW", now)

    def make(mutate=None):
        if mutate:
            mutate(series, now)
        return dict(history=[], forecast=dict(run=first, retrieved=now, series=series, url="", origin="live", sha256="t"),
                    archive=None, errors={}, checked={}, started=now)
    return test_pages, make, now


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_overview_map_has_arrows_and_site_text(lang, snapshot_at):
    test_pages, make, now = snapshot_at
    at = test_pages.run("overview", lang, snapshot=make())
    deck = json.loads(at.get("deck_gl_json_chart")[0].proto.json)
    icons = next(layer for layer in deck["layers"] if layer["@@type"] == "IconLayer")
    assert len(icons["data"]) == 3 and all(r["has_arrow"] for r in icons["data"])
    for row in icons["data"]:  # arrow angle follows the site's own model direction
        assert row["angle"] == pytest.approx(sitemap.icon_angle(compass.to_bearing(float(row["dir_txt"].split("°")[0]))), abs=0.6)
    text = page_text(at)
    assert tr("map_arrow_note", lang, h=80) in text
    assert text.count(f"· 80 {tr('m_unit', lang)}") >= 3  # direction and height on every card


def test_overview_map_without_a_value_for_one_site(snapshot_at):
    def drop_site_2(series, now):
        hour = now.replace(minute=0, second=0, microsecond=0)
        series[1].by_height[80] = [v for v in series[1].by_height[80] if v.valid_at != hour]
    test_pages, make, _ = snapshot_at
    at = test_pages.run("overview", "ka", snapshot=make(drop_site_2))
    deck = json.loads(at.get("deck_gl_json_chart")[0].proto.json)
    icons = next(layer for layer in deck["layers"] if layer["@@type"] == "IconLayer")
    assert len(icons["data"]) == 2  # no invented arrow for the missing site
    assert tr("map_na", "ka") in page_text(at)


# --------------------------------------------------------------------------- text audit

def test_author_credit_has_no_academic_title():
    assert T["author_name"] == {"ka": "გიორგი ხორბალაძე", "en": "Giorgi Khorbaladze"}
    joined = " ".join(v for e in T.values() for v in e.values())
    assert "დოქტ" not in joined and not re.search(r"\bDr\.?\s", joined) and "PhD" not in joined


def test_texts_keep_placeholders_style_and_terminology():
    for key, entry in T.items():
        assert set(re.findall(r"{(\w+)}", entry["ka"])) == set(re.findall(r"{(\w+)}", entry["en"])), key
        for text in entry.values():
            assert "—" not in text, key  # hyphen, never an em dash
        assert "ენერგეტიკული სისტემ" not in entry["ka"].replace("ელექტროენერგეტიკული სისტემ", ""), key


def test_no_unsupported_or_misleading_claims():
    ka = " ".join(e["ka"] for e in T.values())
    en = " ".join(e["en"] for e in T.values())
    assert "გაზომვა არ ხდება" not in ka and "No wind measurements exist" not in en  # not a fact we know
    assert T["last_check"]["ka"] == "გვერდის ბოლო შემოწმება"  # page check time, not source time
    assert "დაგეგმილია" in T["how_text"]["ka"] and "not guaranteed" in T["how_text"]["en"]
    assert "100%" not in T["full_day"]["ka"] and "≥99%" in T["full_day"]["ka"]
    assert "{code}" not in T["source_warning"]["ka"]  # technical code shown separately, not in the message
