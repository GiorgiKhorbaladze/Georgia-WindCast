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
