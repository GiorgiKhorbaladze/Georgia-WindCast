"""Owner copy edits of 18.11.2026: removed texts, D/D-1/D-2 analysis, station names."""

from __future__ import annotations

import pytest
from conftest import page_text

from data import SITES
from i18n import T, tr


def test_station_names_as_requested():
    assert [s.name_ka for s in SITES] == ["„ვინდ ფაუერის“ რუისის ქარის ელექტროსადგური",
                                         "„ზემო ვინდის“ ქარის ელექტროსადგური",
                                         "„ქართლის ქარის ელექტროსადგური“"]


def test_texts_as_requested():
    assert T["tagline"]["ka"] == "ქარის გენერაციის მონიტორინგი და ანალიზი საქართველოში"
    assert "არ ივსება" not in T["cmp_note"]["ka"]
    assert T["cmp_detail_title"]["ka"] == "დათვლის მექანიზმი"
    assert T["cmp_title"]["ka"] == "ქარის გენერაცია: დღეს (D), გუშინ (D-1), გუშინწინ (D-2)"
    assert "ჰიდრო, თბო," in T["bal_intro"]["ka"]
    assert "არ აქვეყნებს" not in T["site_note"]["ka"]
    assert T["ramp_note"]["ka"].endswith("ეს ისტორიული აღწერითი სტატისტიკაა და არა პროგნოზი.")
    assert not any("რეანალიზ" in e["ka"] for e in T.values())


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_overview_has_d2_and_no_removed_notes(lang):
    import test_pages
    at = test_pages.run("overview", lang, test_pages.durable_two_days())
    text = page_text(at)
    assert tr("d2_energy", lang) in text
    for key in ("non_act_note",):
        assert tr(key, lang, n=0, codes="")[:20] not in text


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_removed_notes_are_not_rendered(lang):
    import test_pages
    texts = " ".join(page_text(test_pages.run(p, lang, test_pages.durable_two_days())) for p in ("balance", "analytics", "accuracy", "data"))
    for key in ("bal_flows_note", "bal_mix_sub", "bal_profiles_note", "bal_quality", "facts_only", "acc_intro", "how_text", "disclaimer", "ren_ws", "ren_cmp"):
        assert T[key][lang][:40] not in texts, key


# ------------------------------------------------------------ D / D-1 / D-2 acceptance (Issue #40, A2)

from datetime import date, timedelta  # noqa: E402

import pandas as pd  # noqa: E402

import analytics as an  # noqa: E402


def _const(first_local: str, last_local: str, mw: float = 10.0, skip=lambda t: False):
    idx = pd.date_range(pd.Timestamp(first_local, tz="Asia/Tbilisi"), pd.Timestamp(last_local, tz="Asia/Tbilisi"), freq="3min")
    idx = idx.tz_convert("UTC")
    idx = idx[[not skip(t) for t in idx]]
    return pd.DataFrame({"value_mw": mw, "quality": "ACT"}, index=idx)


def test_day_bounds_follow_the_interval_end_convention_across_midnight():
    first, last = an.day_bounds(date(2026, 11, 16))
    assert first == pd.Timestamp("2026-11-15T20:03Z") and last == pd.Timestamp("2026-11-16T20:00Z")  # 00:03 .. 24:00 Tbilisi
    assert an.local_day(pd.Timestamp("2026-11-16T20:00Z")) == date(2026, 11, 16)  # 24:00 belongs to the day before
    assert an.local_day(pd.Timestamp("2026-11-16T20:03Z")) == date(2026, 11, 17)


def test_matched_elapsed_time_for_d_d1_d2():
    df = _const("2026-11-14 00:03", "2026-11-16 12:00")  # D-2 and D-1 full, D until 12:00
    due = pd.Timestamp("2026-11-16 12:00", tz="Asia/Tbilisi").tz_convert("UTC")
    now = due + pd.Timedelta(minutes=4)
    d = an.day_stats(df, date(2026, 11, 16), now, due)
    d1_same = an.day_stats(df, date(2026, 11, 15), now, due - timedelta(days=1))
    d2_same = an.day_stats(df, date(2026, 11, 14), now, due - timedelta(days=2))
    d2_full = an.day_stats(df, date(2026, 11, 14), now)
    assert d.energy_mwh == d1_same.energy_mwh == d2_same.energy_mwh == pytest.approx(10 * 12)  # same 12 h slice
    assert d2_full.energy_mwh == pytest.approx(10 * 24) and d2_full.complete
    assert d.in_progress and not d2_full.in_progress


def test_d2_without_data_is_empty_not_zero():
    df = _const("2026-11-15 00:03", "2026-11-16 12:00")
    s = an.day_stats(df, date(2026, 11, 14), pd.Timestamp("2026-11-16T08:04Z"))
    assert s.energy_mwh is None and s.stored == 0 and s.expected == 480 and not s.complete


def test_d2_with_a_gap_is_incomplete_and_not_filled():
    hole = lambda t: pd.Timestamp("2026-11-14T06:00Z") <= t < pd.Timestamp("2026-11-14T08:00Z")  # noqa: E731
    df = _const("2026-11-14 00:03", "2026-11-15 00:00", skip=hole)
    s = an.day_stats(df, date(2026, 11, 14), pd.Timestamp("2026-11-16T08:04Z"))
    assert s.stored == 480 - 40 and not s.complete
    assert s.energy_mwh == pytest.approx(10 * 0.05 * 440)  # missing periods are not counted as zero or interpolated


def test_hourly_profile_groups_by_interval_start_hour():
    df = _const("2026-11-14 00:03", "2026-11-15 00:00")
    df.loc[df.index == pd.Timestamp("2026-11-14 01:00", tz="Asia/Tbilisi").tz_convert("UTC"), "value_mw"] = 70.0
    prof = an.hourly_profile(df, date(2026, 11, 14)).set_index("hour")
    assert prof.loc[0, "periods"] == 20 and prof.loc[23, "periods"] == 20 and len(prof) == 24
    assert prof.loc[0, "mean_mw"] == pytest.approx((19 * 10 + 70) / 20)  # 01:00 label closes the 00:57-01:00 interval


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_overview_shows_three_profiles_and_matched_cards(lang):
    import test_pages
    at = test_pages.run("overview", lang, test_pages.durable_two_days())
    text = page_text(at)
    for key in ("cmp_same_time", "cmp_same_time_d2", "d2_energy"):
        assert tr(key, lang) in text
    import json
    fig = next(json.loads(c.proto.spec) for c in at.get("plotly_chart")
               if {tr("today", lang), tr("yesterday", lang), tr("day_d2", lang)} <= {d.get("name") for d in json.loads(c.proto.spec)["data"]})
    assert len(fig["data"]) == 3


def test_map_tooltip_has_no_operating_status():
    from types import SimpleNamespace

    import sitemap
    v = SimpleNamespace(speed_ms=7.0, direction_deg=270.0, valid_at=pd.Timestamp("2026-11-16T16:00Z").to_pydatetime())
    for s in SITES:
        for lang in ("ka", "en"):
            tip = sitemap.site_record(1, s, v, lang)["tip"]
            status = s.status_ka if lang == "ka" else s.status_en
            assert status not in tip and (s.name_ka if lang == "ka" else s.name_en) in tip


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_accuracy_marks_the_reference_as_model_based(lang):
    assert "ERA5" in tr("acc_ref_model", lang, ref=tr("ref_era5", lang))
    assert ("გაზომვ" if lang == "ka" else "measurement") in tr("acc_ref_model", lang, ref="")
