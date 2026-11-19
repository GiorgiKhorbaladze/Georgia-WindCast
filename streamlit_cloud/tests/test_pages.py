"""New pages rendered offline with AppTest in both languages (synthetic, labelled inputs)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import page_text
from i18n import tr
from store import Record
from streamlit.testing.v1 import AppTest
from test_analytics import packet, synthetic

ROOT = Path(__file__).resolve().parents[2]
APP = str(ROOT / "streamlit_cloud/app.py")
NOW = datetime(2026, 11, 16, 16, 10, tzinfo=UTC)  # 20:10 Tbilisi


def durable_two_days(skip_yesterday=0):
    """Yesterday (full or with a hole) and today until NOW, synthetic constant power."""
    start = datetime(2026, 11, 14, 20, 3, tzinfo=UTC)  # 15.11 00:03 Tbilisi
    rows = []
    t, i = start, 0
    while t <= NOW - timedelta(minutes=3):
        if not (skip_yesterday and 100 <= i < 100 + skip_yesterday):
            rows.append(Record(t, "x", 10.0 if t < datetime(2026, 11, 15, 20, 3, tzinfo=UTC) else 20.0, "ACT", t, f"s{i}", "p"))
        t += timedelta(minutes=3)
        i += 1
    return rows


def run(page, lang="ka", durable=None, status=None, archive=None, snapshot=None, timeout=30):
    durable = durable or []
    at = AppTest.from_file(APP, default_timeout=timeout)
    patches = [
        patch("data.utcnow", return_value=NOW),
        patch("history.HistoryReader.records", side_effect=lambda s, e, n: [r for r in durable if s <= r.period_label_utc <= e]),
        patch("history.HistoryReader.status", return_value=status),
        patch("history.HistoryReader.forecast_archive", return_value=archive or []),
        patch("data.SourceCache.snapshot", return_value=snapshot or dict(history=[], forecast=None, archive=None, errors={}, checked={}, started=NOW)),
    ]
    for p in patches:
        p.start()
    try:
        at.run()
        if lang == "en":
            at.sidebar.radio[0].set_value("English").run()
        at.sidebar.radio[1].set_value(page).run()
    finally:
        for p in patches:
            p.stop()
    assert not at.exception, at.exception
    return at


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_overview_comparison_full_yesterday(lang):
    text = page_text(run("overview", lang, durable_two_days()))
    assert "240" in text  # yesterday: 10 MW x 24 h, complete
    assert ("საკმარისად სრული დღე (≥99%)" if lang == "ka" else "sufficiently complete day (≥99%)") in text
    assert "+" in text and "100.0%" in text  # today 20 MW vs 10 MW at the same time


def test_overview_marks_incomplete_yesterday():
    text = page_text(run("overview", "ka", durable_two_days(skip_yesterday=60)))
    assert "არასრული დღე" in text and "87.5%" in text  # 420 / 480, never extrapolated


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_analytics_page_stats_and_download(lang):
    at = run("analytics", lang, durable_two_days())
    text = page_text(at)
    assert ("ჯამური გამომუშავება" if lang == "ka" else "Total energy") in text
    assert at.get("download_button")
    assert at.get("plotly_chart")


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_forecast_page_withholds_the_mw_forecast_by_default(lang):
    # Issue #40 B: the national MW forecast stays suspended until the owner switches it on.
    import mwmodel
    assert mwmodel.PUBLISH_FORECAST is False
    table, df = synthetic(24 * 20)  # enough paired hours: still nothing may be shown
    shift = (NOW.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)) - table.index[-1].to_pydatetime()
    durable = [Record(t.to_pydatetime() + shift, "x", float(v), "ACT", NOW, f"h{k}", "p")
               for k, (t, v) in enumerate(df["value_mw"].items())]
    at = run("forecast", lang, durable)
    assert tr("mw_suspended", lang) in " ".join(i.value for i in at.info)
    assert tr("mw_band", lang) not in page_text(at) and "MAE" not in page_text(at)
    assert ("არაოფიციალური" if lang == "ka" else "Unofficial") in page_text(at)


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_forecast_page_insufficient_history_is_explicit(lang, monkeypatch):
    monkeypatch.setattr("mwmodel.PUBLISH_FORECAST", True)  # behaviour once the owner switches it on
    at = run("forecast", lang, durable_two_days())
    infos = " ".join(i.value for i in at.info)
    assert ("168" in infos) and ("საათი" in infos if lang == "ka" else "h" in infos)
    assert ("არაოფიციალური" if lang == "ka" else "Unofficial") in page_text(at)


def test_forecast_page_shows_model_vs_baselines_when_trained(monkeypatch):
    monkeypatch.setattr("mwmodel.PUBLISH_FORECAST", True)
    table, df = synthetic(24 * 20)
    # align the synthetic hourly table to whole hours ending two hours before NOW
    shift = (NOW.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)) - table.index[-1].to_pydatetime()
    table.index = table.index + shift
    durable = [Record(t.to_pydatetime() + shift, "x", float(v), "ACT", NOW, f"h{k}", "p")
               for k, (t, v) in enumerate(df["value_mw"].items())]
    hist = dict(series=[], sha256="synthetic", retrieved=NOW, url="")

    def weather_table(series, n):
        return table if series == [] else table

    with patch("history.HistoryReader.hist_forecast", return_value=hist), patch("mwmodel.weather_table", side_effect=weather_table):
        at = run("forecast", "en", durable)
    assert all("168" not in i.value for i in at.info)  # trained, not "insufficient"
    table = at.dataframe[0].value
    methods = list(table.iloc[:, 0])
    assert methods[:2] == ["Model", "Climatology (hourly mean)"] and any(m.startswith("Persistence") for m in methods)
    mae = dict(zip(methods, table["MAE, MW"], strict=True))
    assert mae["Model"] < mae["Climatology (hourly mean)"]  # held-out comparison shown honestly
    assert any("MAE" in i.value for i in at.info) and not at.warning  # skill stated, with sample size


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_accuracy_page_scores_archive(lang):
    t0 = NOW - timedelta(days=3)
    runs = [packet(t0 + timedelta(hours=6 * i), lambda v, k: 6.0 + 0.05 * k) for i in range(10)]
    for p in runs:
        p["series"] = p["series"] * 3  # three sites
    at = run("accuracy", lang, archive=runs)
    assert ("წინსწრების დრო" if lang == "ka" else "Lead time") in page_text(at)
    assert at.get("plotly_chart")


def test_accuracy_page_without_archive_explains():
    at = run("accuracy", "ka")
    assert at.info and "არქივი" in at.info[0].value


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_data_page_health_and_gaps(lang):
    status = {"last_success_at": (NOW - timedelta(minutes=10)).isoformat(), "latest_label_utc": (NOW - timedelta(minutes=6)).isoformat(),
              "last_run": {"requested": 30, "inserted": 25, "backfilled": 12, "lookback_used_hours": 21.0},
              "deep_backfill": {"cursor": (NOW - timedelta(days=5)).isoformat(), "done": False}}
    at = run("data", lang, durable_two_days(skip_yesterday=60), status=status)
    text = page_text(at)
    assert tr("h_healthy", lang) in text and tr("h_age_note", lang).split(";")[0] in text
    assert "12" in text and "21" in text  # recovered periods and widened window are visible
    gaps = at.dataframe[0].value  # missing intervals table
    assert len(gaps) == 1 and int(gaps.iloc[0, 2]) == 60


def test_data_page_stale_collector():
    status = {"last_success_at": (NOW - timedelta(hours=9)).isoformat(), "latest_label_utc": (NOW - timedelta(hours=9)).isoformat()}
    assert "ყურადღება" in page_text(run("data", "ka", status=status))


def test_kpi_labels_say_wind_generation_not_consumption():
    text = page_text(run("overview", "ka", durable_two_days()))
    assert "ქარის გენერაციის მაქსიმუმი დღეს" in text and "3-წუთიანი საშუალო" in text and "ქარის გენერაცია" in text
    assert "ხარისხის კოდი" not in text and "ACT" not in text  # no quality codes in the public UI
    assert "ქარის გამომუშავება დღეს" in text and "ქარის გამომუშავება გუშინ" in text
    assert "დღის პიკი" not in text  # ambiguous (reads as demand peak)


def balance_rows():
    from store import BalanceRecord
    start = NOW - timedelta(hours=24)
    out, t, k = [], start, 0
    while t <= NOW - timedelta(minutes=3):
        out.append(BalanceRecord(t, "x", 1500.0, 300.0, 200.0, 0.0, 2000.0, 2050.0, "hydro:SUB", NOW, f"b{k}", "p"))
        t += timedelta(minutes=3)
        k += 1
    return out


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_balance_page_renders_mix_profiles_and_derived_import(lang):
    rows = balance_rows()
    with patch("history.HistoryReader.balance", side_effect=lambda s, e, n: [r for r in rows if s <= r.period_label_utc <= e]):
        at = run("balance", lang)
    text = page_text(at)
    assert "2 050" in text and "2 000" in text  # consumption and generation now
    assert ("იმპორტი (გამოთვლილი)" if lang == "ka" else "import (derived)") in text  # 50 MW derived net import
    assert len(at.get("plotly_chart")) >= 4 and at.get("download_button")
    assert ("ქარის წილი მოხმარებაში" if lang == "ka" else "Wind share of consumption") in text
    assert "9.8%" in text  # 200 / 2050 MW


def test_overview_has_separate_balance_chart():
    rows = balance_rows()
    with patch("history.HistoryReader.balance", side_effect=lambda s, e, n: [r for r in rows if s <= r.period_label_utc <= e]):
        at = run("overview", "ka", durable_two_days())
    assert any("ბალანსი" in h.value for h in at.subheader)


def test_author_block_with_photo_and_linkedin():
    at = run("overview", "en", durable_two_days())
    side = " ".join(m.value for m in at.sidebar.markdown)
    assert "Giorgi Khorbaladze" in side and "Dr." not in side and "data:image/jpeg;base64," in side
    assert "linkedin.com/in/dr-giorgi-khorbaladze-academician-b1b744103" in side


def test_cached_reader_is_recreated_after_a_code_reload():
    """Regression: an instance of an older HistoryReader class (missing new methods) must not survive."""
    import history
    at = run("forecast", "en", durable_two_days())
    assert not at.exception

    class Reloaded(history.HistoryReader):  # stands in for the class after a redeploy reload
        pass

    with patch("history.HistoryReader", Reloaded):
        at2 = run("accuracy", "en")
    assert not at2.exception


def test_balance_page_shows_import_and_export_separately():
    from store import BalanceRecord
    rows = [BalanceRecord(NOW - timedelta(minutes=3 * k), "x", 1500.0, 300.0, 200.0, 0.0, 2000.0, 2010.0, "q", NOW, f"g{k}",
                          "gse-balance-03m/2", import_mw=34.71, export_mw=24.71) for k in range(1, 60)]
    with patch("history.HistoryReader.balance", side_effect=lambda s, e, n: [r for r in rows if s <= r.period_label_utc <= e]):
        at = run("balance", "ka")
    text = page_text(at)
    assert "იმპორტი ახლა" in text and "34.71" in text
    assert "ექსპორტი ახლა" in text and "24.71" in text
    assert "წმინდა იმპორტი (გამოთვლილი)" not in text  # gross flows, not the derived net
