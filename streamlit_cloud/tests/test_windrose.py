"""Wind rose (Issue #33, feature 3): FROM sectors, speed bands, valid-hour denominator, calm."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.ingestion.openmeteo import HourValue
from conftest import page_text

import windrose as wr
from i18n import tr

T0 = datetime(2026, 11, 6, 0, tzinfo=UTC)


def vals(pairs):
    return [HourValue(T0 + timedelta(hours=k), s, d) for k, (s, d) in enumerate(pairs)]


@pytest.mark.parametrize("deg, s16, s8", [(0, 0, 0), (359, 0, 0), (1, 0, 0), (11.2, 0, 0), (11.3, 1, 0),
                                          (22.5, 1, 1), (90, 4, 2), (180, 8, 4), (270, 12, 6), (348.7, 15, 0), (360, 0, 0)])
def test_sector_wraps_and_is_centred(deg, s16, s8):
    assert wr.sector_of(deg, 16) == s16 and wr.sector_of(deg, 8) == s8


def test_speed_bands_and_calm():
    assert wr.band_of(0.4) is None  # calm (Beaufort 0)
    assert [wr.band_of(x) for x in (0.5, 2.99, 3.0, 6.5, 9.0, 11.99, 12.0, 30)] == [0, 0, 1, 2, 3, 3, 4, 4]
    assert wr.band_labels() == ["0.5-3", "3-6", "6-9", "9-12", "≥12"]


def test_percentages_use_valid_hours_and_calm_is_separate():
    r = wr.rose(vals([(5, 359), (5, 1), (7, 90), (0.2, 200), (None, 90), (6, None)]), 16)
    assert r.n_valid == 4 and r.n_missing == 2  # missing speed or direction is excluded and counted
    assert r.table.loc[0.0, "3-6"] == pytest.approx(50.0)  # 359° and 1° in the north sector
    assert r.table.loc[90.0, "6-9"] == pytest.approx(25.0)
    assert r.calm_pct == pytest.approx(25.0)
    assert r.table.to_numpy().sum() + r.calm_pct == pytest.approx(100.0)
    assert r.first == T0 and r.last == T0 + timedelta(hours=5)


def test_empty_and_invalid_inputs():
    r = wr.rose([], 8)
    assert r.n_valid == 0 and r.table.to_numpy().sum() == 0 and r.first is None
    with pytest.raises(ValueError):
        wr.rose([], 12)


@pytest.mark.parametrize("lang", ["ka", "en"])
def test_analytics_page_shows_the_rose_from_one_source(lang, monkeypatch):
    import test_pages
    from app.ingestion.openmeteo import REANALYSIS, parse_response
    from test_adapter import FIXTURES
    era5 = dict(series=parse_response((FIXTURES / "openmeteo/real_archive_era5_3sites_20261106.json").read_bytes(), 3, REANALYSIS.heights),
                retrieved=test_pages.NOW)
    snapshot = dict(history=[], forecast=None, archive=era5, errors={}, checked={}, started=test_pages.NOW)
    at = test_pages.run("analytics", lang, test_pages.durable_two_days(), snapshot=snapshot)
    text = page_text(at)
    assert tr("rose_note", lang) in text
    assert tr("rose_src_era5", lang) in text and ("10 მ" if lang == "ka" else "10 m") in text
    assert tr("rose_title", "ka") == "ქარის ვარდი"  # editorial audit 21.11.2026: no English gloss
