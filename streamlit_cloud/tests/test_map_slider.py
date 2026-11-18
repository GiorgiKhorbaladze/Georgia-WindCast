"""Time-controlled site map (Issue #33, feature 2): genuine model hours only, nothing in between."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from app.ingestion.openmeteo import FORECAST, HourValue, parse_response
from conftest import page_text
from test_adapter import FORECAST_BODY

import compass
import sitemap
from i18n import tr

H0 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


class Loc:
    def __init__(self, by_height):
        self.by_height = by_height


def packet(site_values):
    """site_values: list (per site) of {height: [(hour_offset, speed, direction), ...]}."""
    series = [Loc({h: [HourValue(H0 + timedelta(hours=k), s, d) for k, s, d in vals] for h, vals in site.items()})
              for site in site_values]
    return dict(run=H0 - timedelta(hours=6), series=series)


def test_hours_are_only_those_in_the_run_from_the_current_hour():
    p = packet([{80: [(-1, 5, 90), (0, 5, 90), (1, 6, 100), (3, 7, 110)]},  # hour 2 absent in the run
                {80: [(0, 4, 80), (5, 4, None)]}])  # hour 5 without direction anywhere
    hours = sitemap.forecast_hours(p, H0 + timedelta(minutes=40), 80)
    assert hours == [H0, H0 + timedelta(hours=1), H0 + timedelta(hours=3)]  # no -1, no invented 2, no 5


def test_horizon_limit_and_height_are_respected():
    p = packet([{80: [(k, 5, 90) for k in range(0, 100)], 120: [(0, 6, 90)]}])
    assert len(sitemap.forecast_hours(p, H0, 80)) == 73  # 0..72 h
    assert sitemap.forecast_hours(p, H0, 120) == [H0]
    assert sitemap.forecast_hours(p, H0, 10) == [] and sitemap.forecast_hours(None, H0) == []


def test_value_at_is_an_exact_hour_match():
    p = packet([{80: [(0, 5, 90), (2, 7, 270)]}])
    assert sitemap.value_at(p, 0, 80, H0 + timedelta(hours=2)).direction_deg == 270
    assert sitemap.value_at(p, 0, 80, H0 + timedelta(hours=1)) is None  # not interpolated from 0 and 2
    assert sitemap.value_at(None, 0, 80, H0) is None


def test_next_hour_steps_and_wraps():
    hours = [H0, H0 + timedelta(hours=1), H0 + timedelta(hours=3)]
    assert sitemap.next_hour(hours, H0) == hours[1]
    assert sitemap.next_hour(hours, hours[2]) == H0  # wraps to the start of the run
    assert sitemap.next_hour(hours, hours[0], -1) == hours[2]
    assert sitemap.next_hour(hours, None) == H0 and sitemap.next_hour([], H0) is None


@pytest.mark.parametrize("frm", [0, 90, 180, 270, 359])
def test_arrow_follows_the_selected_hour(frm):
    p = packet([{80: [(0, 8, 10), (1, 8, frm)]}])
    from data import SITES
    rec = sitemap.site_record(1, SITES[0], sitemap.value_at(p, 0, 80, H0 + timedelta(hours=1)), "ka")
    assert rec["angle"] == pytest.approx(sitemap.icon_angle(compass.to_bearing(frm)))
    assert rec["meta"] == tr("map_meta", "ka", h=80, t="17.11 11:00")


# --------------------------------------------------------------------------- page (AppTest)

@pytest.fixture
def overview(monkeypatch):
    import test_pages
    series = parse_response(FORECAST_BODY, 3, FORECAST.heights)
    first = series[0].by_height[80][0].valid_at
    now = first + timedelta(hours=1, minutes=10)
    monkeypatch.setattr(test_pages, "NOW", now)
    snapshot = dict(history=[], forecast=dict(run=first, retrieved=now, series=series, url="", origin="live", sha256="t"),
                    archive=None, errors={}, checked={}, started=now)
    return test_pages, snapshot, series, now


def deck_rows(at):
    deck = json.loads(at.get("deck_gl_json_chart")[0].proto.json)
    return next(layer for layer in deck["layers"] if layer["@@type"] == "IconLayer")["data"]


def interact(test_pages, lang, snapshot, now, action):
    """Run the page and one widget interaction with the offline patches active for both runs."""
    from contextlib import ExitStack
    from unittest.mock import patch

    from streamlit.testing.v1 import AppTest
    with ExitStack() as stack:
        for target, value in (("data.utcnow", now), ("history.HistoryReader.status", None),
                              ("history.HistoryReader.forecast_archive", []), ("data.SourceCache.snapshot", snapshot)):
            stack.enter_context(patch(target, return_value=value))
        stack.enter_context(patch("history.HistoryReader.records", return_value=[]))
        at = AppTest.from_file(test_pages.APP, default_timeout=30)
        at.run()
        if lang == "en":
            at.sidebar.radio[0].set_value("English").run()
        action(at)
    assert not at.exception, at.exception
    return at


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_slider_selects_a_later_model_hour(lang, overview):
    test_pages, snapshot, series, now = overview
    hours = sitemap.forecast_hours(snapshot["forecast"], now, 80)
    target = hours[5]
    at = interact(test_pages, lang, snapshot, now, lambda at: at.select_slider[0].set_value(target).run())
    assert len(at.select_slider[0].options) == len(hours)  # genuine run hours only
    expected = series[0].by_height[80]
    want = next(v for v in expected if v.valid_at == target)
    row = deck_rows(at)[0]
    assert row["angle"] == pytest.approx(sitemap.icon_angle(compass.to_bearing(want.direction_deg)))
    assert at.select_slider[0].value == target  # the slider shows the selected valid hour
    assert tr("map_time_note", lang) in page_text(at)


def test_height_selector_changes_values_and_label(overview):
    test_pages, snapshot, series, now = overview
    at = interact(test_pages, "ka", snapshot, now, lambda at: at.selectbox(key="map_height").set_value(120).run())
    assert "· 120 მ" in page_text(at)
    assert tr("map_arrow_note", "ka", h=120) in page_text(at)
