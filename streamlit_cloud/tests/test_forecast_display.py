"""Website MW forecast section (release switch off by default): units, Georgia time, source
integrity, freshness, missing/invalid data, no invented values, gate on live evidence only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import page_text
from streamlit.testing.v1 import AppTest

import forecast_display as fd
from forecasting import gate
from i18n import T, tr

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
CUT = NOW - timedelta(minutes=15)


def latest_csv(cut=CUT, rows=None):
    head = "model_id,cadence,issued,cutoff,valid_from,valid_to,mw"
    rows = rows or [f"damped_trend,1h,{(cut + timedelta(minutes=3)).isoformat()},{cut.isoformat()},"
                    f"{(cut + timedelta(hours=h - 1)).isoformat()},{(cut + timedelta(hours=h)).isoformat()},{10.0 * h}"
                    for h in (1, 2, 3, 6)]
    return head + "\n" + "\n".join(rows) + "\n"


def test_parse_keeps_units_and_measures_horizon_from_the_cutoff():
    lat = fd.parse(latest_csv())
    assert list(lat.rows.horizon_min) == [60, 120, 180, 360] and list(lat.rows.mw) == [10.0, 20.0, 30.0, 60.0]
    assert lat.dropped == 0 and not fd.is_stale(lat.rows, NOW)


def test_times_are_shown_in_georgia_time():
    assert fd.local(datetime(2026, 11, 22, 6, 0, tzinfo=UTC)) == "22.11.2026 10:00"  # UTC+4


@pytest.mark.parametrize("bad", ["nan", "inf", "-50", "9999"])
def test_invalid_values_are_dropped_never_repaired(bad):
    rows = latest_csv().splitlines()[1:]
    rows[1] = rows[1].rsplit(",", 1)[0] + "," + bad
    lat = fd.parse(latest_csv(rows=rows))
    assert lat.dropped == 1 and len(lat.rows) == 3 and float(bad) not in set(lat.rows.mw)


def test_broken_intervals_and_issue_before_cutoff_are_dropped():
    c = CUT.isoformat()
    rows = [f"p,1h,{c},{c},{(CUT + timedelta(hours=1)).isoformat()},{CUT.isoformat()},5",  # empty interval
            f"p,1h,{(CUT - timedelta(minutes=5)).isoformat()},{c},{c},{(CUT + timedelta(hours=1)).isoformat()},5"]
    assert fd.parse(latest_csv(rows=rows)).rows.empty


@pytest.mark.parametrize("text", [None, "", "a,b\n1,2\n"])
def test_missing_or_malformed_file_yields_nothing(text):
    assert fd.parse(text).rows.empty


def test_stale_forecast_is_not_current():
    lat = fd.parse(latest_csv(cut=NOW - timedelta(hours=3)))
    assert fd.is_stale(lat.rows, NOW)


def test_one_issue_per_curve_and_no_band_without_genuine_quantiles():
    rows = latest_csv().splitlines()[1:]
    older = rows[0].replace(CUT.isoformat(), (CUT - timedelta(minutes=15)).isoformat())
    s = fd.series(fd.parse(latest_csv(rows=rows + [older])).rows, "damped_trend", "1h")
    assert s.issued.nunique() == 1 and not fd.has_band(s)


def board(days=30, cases=800, ci=(0.05, 0.2), bias=1.0, mae=10.0, late=0.02):
    row = dict(model_id="damped_trend", cadence="1h", horizon_min=60, days=days, cases=cases,
               skill_90ci=list(ci), bias=bias, mae=mae)
    return {"live": {"coverage": {"matured": 1000, "complete": 950, "late_share": late},
                     "leaderboard": [row, dict(row, model_id="persistence")]},
            "backtest": {"leaderboard": [dict(row, days=99, cases=99999)]}}


def test_gate_uses_only_live_evidence_and_all_criteria():
    assert gate.passes(gate.evaluate(board()), "damped_trend", "1h", 60)
    for kw in (dict(days=14), dict(cases=100), dict(ci=(-0.01, 0.2)), dict(bias=5.0), dict(late=0.3)):
        g = gate.evaluate(board(**kw))
        assert not g["passing"] and g["rows"][0]["reasons"], kw
    assert gate.evaluate({"backtest": board()["backtest"]})["rows"] == []  # backtest never counts
    assert all(r["model_id"] != "persistence" for r in gate.evaluate(board())["rows"])


def test_release_switch_is_off_and_texts_exist_in_both_languages():
    import mwmodel
    assert mwmodel.PUBLISH_FORECAST is False
    for k, v in T.items():
        if k.startswith("fcd_"):
            assert v["ka"] and v["en"] and "—" not in v["ka"] + v["en"] and "GSE" not in v["ka"], k


APP = str(Path(__file__).resolve().parents[1] / "app.py")
ACTUAL_SEEN: list[int] = []


def fake_records(self, start, end, now):
    """Collector rows for the last 24 h (no network): official values, not invented by the page."""
    from store import Record
    out = [Record(NOW - timedelta(minutes=3 * k), "", 42.0, "ACT", NOW, "x" * 64, "1") for k in range(1, 480)]
    ACTUAL_SEEN.append(len(out))
    return out
FIX = Path(__file__).resolve().parent / "fixtures" / "forecast"


def run_page(lang, publish, latest):
    import streamlit as st

    def fetch(path, base=None):
        if path.endswith("latest.csv"):
            calls.append(path)
            return latest
        f = FIX / path.split("/")[-1]
        return f.read_text(encoding="utf-8") if f.exists() else None
    calls: list[str] = []
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=60)
    with patch("forecast_page.fetch", side_effect=fetch), patch("mwmodel.PUBLISH_FORECAST", publish), \
            patch("data.utcnow", return_value=NOW), patch("forecast_page._actuals", side_effect=lambda reader, now: fd.actual_frame(fake_records(None, 0, 0, now))):
        at.run()
        if lang == "en":
            at.sidebar.radio[0].set_value("English").run()
        at.sidebar.radio[1].set_value("gen_forecast").run()
    assert not at.exception, at.exception
    return at, calls


def test_page_with_switch_off_never_downloads_values():
    at, calls = run_page("en", False, latest_csv())
    assert calls == [] and tr("fcd_title", "en") not in [s.value for s in at.subheader]


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_page_with_switch_on_shows_a_labelled_fresh_forecast(lang):
    at, calls = run_page(lang, True, latest_csv())
    text = page_text(at)
    assert calls and tr("fcd_title", lang) in [s.value for s in at.subheader]
    assert tr("fcd_label", lang) in text and tr("fcd_no_band", lang) in [c.value for c in at.caption]


def test_page_with_switch_on_hides_stale_and_missing():
    at, _ = run_page("en", True, latest_csv(cut=NOW - timedelta(hours=5)))
    assert any(tr("fcd_stale", "en").split("(")[0] in w.value for w in at.warning)
    at, _ = run_page("en", True, None)
    assert any(i.value == tr("fcd_unavailable", "en") for i in at.info)


def test_actual_gse_generation_is_overlaid_separately():
    ACTUAL_SEEN.clear()
    at, _ = run_page("en", True, latest_csv())
    assert ACTUAL_SEEN == [479]
    names = [tr("fcd_actual", "en"), tr("fcd_forecast", "en")]
    chart = at.get("plotly_chart")[0].proto.spec
    assert all(n in chart for n in names)
