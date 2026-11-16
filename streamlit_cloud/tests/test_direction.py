"""Wind direction text, the forecast chart and the MW skill label (Issue #18, owner UX feedback)."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from app.ingestion.openmeteo import FORECAST, parse_response
from conftest import page_text
from test_adapter import FORECAST_BODY

import compass
from charts import series_figure, series_frame, time_ticks, wall
from i18n import tr


# ------------------------------------------------------------------------------- compass helpers

@pytest.mark.parametrize("deg, ka, en", [
    (0, "ჩრდილოეთიდან", "from north"),
    (360, "ჩრდილოეთიდან", "from north"),
    (1, "ჩრდილოეთიდან", "from north"),
    (359, "ჩრდილოეთიდან", "from north"),
    (45, "ჩრდილო-აღმოსავლეთიდან", "from north-east"),
    (90, "აღმოსავლეთიდან", "from east"),
    (180, "სამხრეთიდან", "from south"),
    (270, "დასავლეთიდან", "from west"),
    (-90, "დასავლეთიდან", "from west"),
    (22.4, "ჩრდილოეთიდან", "from north"),
    (22.5, "ჩრდილო-აღმოსავლეთიდან", "from north-east"),
])
def test_sector_names_follow_the_from_convention(deg, ka, en):
    assert compass.sector(deg, "ka") == ka
    assert compass.sector(deg, "en") == en


def test_label_keeps_exact_degrees_next_to_the_text():
    assert compass.label(270, "ka") == "270° - დასავლეთიდან"
    assert compass.label(270, "en") == "270° - from west"
    assert compass.label(359.6, "en") == "0° - from north"  # rounds into the same sector, never "360°"
    assert compass.label(1.0, "ka") == "1° - ჩრდილოეთიდან"


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_missing_direction_is_a_dash_not_a_guess(missing):
    assert compass.sector(missing) is None
    assert compass.label(missing, "ka") == "-"
    assert compass.difference(missing, 10) is None


def test_direction_difference_is_circular():
    assert compass.difference(359, 1) == 2
    assert compass.difference(1, 359) == 2
    assert compass.difference(0, 360) == 0
    assert compass.difference(90, 270) == 180
    assert compass.difference(10, 350) == 20


# ---------------------------------------------------------------------------- chart construction

def values(directions, speeds=None, start=datetime(2026, 11, 17, 0, 0, tzinfo=UTC)):
    from app.ingestion.openmeteo import HourValue
    speeds = speeds or [8.0] * len(directions)
    return [HourValue(start + timedelta(hours=k), s, d) for k, (s, d) in enumerate(zip(speeds, directions, strict=True))]


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_tooltip_shows_degrees_and_localized_sector(lang):
    fig = series_figure(series_frame(values([0, 90, 180, 270, 359])), lang, 80)
    speed, direction = fig.data
    labels = [row[0] for row in direction.customdata]
    assert labels == [compass.label(d, lang) for d in (0, 90, 180, 270, 359)]
    assert "%{customdata[0]}" in direction.hovertemplate
    assert direction.mode == "markers"  # never a line: 359 -> 1 must not draw a 358° swing
    assert speed.connectgaps is False
    # both traces on one x axis, so one hover shows speed and direction for the same hour
    assert (speed.xaxis or "x") == (direction.xaxis or "x") == "x" and {speed.yaxis, direction.yaxis} == {"y", "y2"}
    assert fig.layout.hoversubplots == "axis" and fig.layout.hovermode == "x unified"
    texts = [a.text for a in fig.layout.annotations]
    assert tr("direction_short", lang) in texts and any("80 m" in t for t in texts)


def test_wraparound_points_stay_separate_values():
    fig = series_figure(series_frame(values([358, 359, 1, 2])), "en")
    assert list(fig.data[1].y) == [358, 359, 1, 2]  # raw, not unwrapped or averaged
    assert fig.data[1].mode == "markers"


def test_light_wind_points_are_hollow_and_flagged():
    fig = series_figure(series_frame(values([90, 90], speeds=[1.5, 9.0])), "ka")
    direction = fig.data[1]
    assert list(direction.marker.symbol) == ["circle-open", "circle"]
    assert direction.customdata[0][1].endswith(tr("calm_short", "ka")) and direction.customdata[1][1] == ""


def test_missing_direction_and_missing_hour_remain_gaps():
    vals = values([90, None, 180, 200], speeds=[5.0, None, 6.0, 7.0])
    del vals[3]  # the upstream omitted the last-but-one hour entirely ...
    vals.append(values([210], speeds=[7.5], start=vals[-1].valid_at + timedelta(hours=2))[0])
    frame = series_frame(vals)
    assert len(frame) == 5  # ... and the hour is reindexed, not skipped
    fig = series_figure(frame, "en")
    speed, direction = fig.data
    assert math.isnan(speed.y[1]) and math.isnan(speed.y[3])
    assert math.isnan(direction.y[1]) and math.isnan(direction.y[3])
    assert direction.customdata[1][0] == "-"


def test_chart_reproduces_upstream_values_exactly():
    """Regression: abrupt speed changes come from the model values, not from parsing or the time axis."""
    series = parse_response(FORECAST_BODY, 3, FORECAST.heights)
    vals = series[0].by_height[80]
    fig = series_figure(series_frame(vals), "en", 80)
    speed, direction = fig.data
    assert list(speed.x) == [wall(v.valid_at) for v in vals]  # one point per hour, no shift
    assert [None if math.isnan(y) else y for y in speed.y] == [v.speed_ms for v in vals]
    assert [None if math.isnan(y) else y for y in direction.y] == [v.direction_deg for v in vals]


def test_time_ticks_are_readable_on_a_three_day_axis():
    start = pd.Timestamp("2026-11-16T20:00:00Z")  # 17.11 00:00 Tbilisi
    vals, text = time_ticks(start, start + pd.Timedelta(hours=72))
    assert text == ["17.11", "12:00", "18.11", "12:00", "19.11", "12:00", "20.11"]  # date marks 00:00
    assert vals[0] == "2026-11-17T00:00:00" and vals[1] == "2026-11-17T12:00:00"
    _, short = time_ticks(start, start + pd.Timedelta(hours=30))
    assert short[:3] == ["17.11", "06:00", "12:00"]


# --------------------------------------------------------------------------- pages (AppTest)

@pytest.fixture
def forecast_now(monkeypatch):
    import test_pages
    series = parse_response(FORECAST_BODY, 3, FORECAST.heights)
    first = series[0].by_height[80][0].valid_at
    now = first + timedelta(hours=1, minutes=10)
    monkeypatch.setattr(test_pages, "NOW", now)
    snapshot = dict(history=[], forecast=dict(run=first, retrieved=now, series=series, url="", origin="live", sha256="t"),
                    archive=None, errors={}, checked={}, started=now)
    return test_pages, snapshot


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_forecast_page_explains_direction_and_labels_now(lang, forecast_now):
    test_pages, snapshot = forecast_now
    at = test_pages.run("forecast", lang, snapshot=snapshot)
    text = page_text(at)
    assert tr("wx_dir_note", lang) in text
    assert ("270° - დასავლეთიდან" if lang == "ka" else "270° - from west") in text
    chart = json.dumps(json.loads(at.get("plotly_chart")[-1].proto.spec), ensure_ascii=False)
    assert tr("now", lang) in chart and ("ჩრდილო" if lang == "ka" else "from ") in chart
    table = at.dataframe[-1].value
    assert list(table.columns) == [tr("speed", lang), tr("direction", lang), tr("direction_text", lang)]


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_map_cards_use_localized_direction(lang, forecast_now):
    test_pages, snapshot = forecast_now
    at = test_pages.run("overview", lang, snapshot=snapshot)
    text = page_text(at)
    sectors = compass.SECTORS[lang]
    assert any(f"° - {s}" in text for s in sectors)
    assert not any(f"({c})" in text for c in ("N", "NE", "E", "SE", "S", "SW", "W", "NW"))


# ------------------------------------------------------------------------------- MW skill label

@pytest.mark.parametrize("model, clim, p24, p1, expect", [
    (40.0, 50.0, 60.0, 10.0, ("climatology", 50.0)),   # 1 h persistence is not a day-ahead yardstick
    (40.0, 50.0, 30.0, None, ("persistence24", 30.0)),
    (40.0, 35.0, None, None, ("climatology", 35.0)),
])
def test_fair_baseline_for_day_ahead_skill(model, clim, p24, p1, expect):
    import mwmodel
    res = mwmodel.ModelResult("ok", 200, model=dict(mae=model), climatology=dict(mae=clim),
                              persistence={h: dict(mae=v) for h, v in ((1, p1), (24, p24)) if v is not None})
    assert mwmodel.fair_baseline(res) == expect
