from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest

from conftest import META, REAL_NRE, GseServer, relabel, utc, weather_handler
from windcast_demo import core

# 2026-11-15 00:20:00 Tbilisi = 2026-11-14 20:20 UTC; newest due label 00:18 local (lag 75 s).
NOW = utc(2026, 11, 14, 20, 20, 0)


def window(gse: GseServer, periods: int = 10) -> core.GseRecentWindow:
    return core.GseRecentWindow(gse.client, window_periods=periods)


def test_window_fills_from_source_and_shows_gaps(gse: GseServer) -> None:
    gse.missing = {"00:12"}
    snap = window(gse).snapshot(NOW)
    assert len(snap.points) == 10
    assert snap.points[-1].label_utc == utc(2026, 11, 14, 20, 18)
    assert snap.points[0].label_utc == utc(2026, 11, 14, 19, 51)
    gap = [p for p in snap.points if p.value_mw is None]
    assert [p.label_utc for p in gap] == [utc(2026, 11, 14, 20, 12)]
    assert snap.latest is not None and snap.latest.value_mw == pytest.approx(73.599297)
    assert snap.status == "fresh" and snap.error is None


def test_quality_other_than_act_is_unverified_not_fresh(gse: GseServer) -> None:
    gse.base = REAL_NRE
    assert window(gse).snapshot(NOW).status == "unverified"


def test_old_reading_is_stale_and_empty_is_unavailable(gse: GseServer) -> None:
    w = window(gse, periods=3)
    w.snapshot(NOW)
    later = NOW + timedelta(minutes=30)
    gse.override = lambda name: httpx.Response(404, headers={"content-type": "text/html"})
    snap = w.snapshot(later)
    assert snap.latest is None and snap.status == "unavailable"  # old periods left the window
    w2 = window(gse, periods=20)
    assert w2.snapshot(NOW).status == "unavailable"


def test_published_files_are_fetched_once_and_refresh_is_throttled(gse: GseServer) -> None:
    w = window(gse)
    w.snapshot(NOW)
    assert len(gse.requests) == 10
    w.snapshot(NOW + timedelta(seconds=10))  # within min_refresh: no requests at all
    assert len(gse.requests) == 10
    w.snapshot(NOW + timedelta(minutes=3))  # one new period only
    assert len(gse.requests) == 11


def test_old_missing_period_is_abandoned_newest_is_rechecked(gse: GseServer) -> None:
    gse.missing = {"00:12", "00:18"}
    w = window(gse)
    for i in range(5):
        w.snapshot(NOW + timedelta(seconds=31 * i))
    old = [r for r in gse.requests if r.endswith("_0012.XML")]
    newest = [r for r in gse.requests if r.endswith("_0018.XML")]
    assert len(old) == 3  # gave up after 3 attempts: stays a gap
    assert len(newest) == 5


def test_mislabelled_file_is_refused(gse: GseServer) -> None:
    gse.override = lambda name: httpx.Response(
        200,
        headers={"content-type": "application/xml"},
        content=relabel(gse.base, "14.11.2026 23:00:00"),
    )
    snap = window(gse).snapshot(NOW)
    assert snap.latest is None
    assert snap.error == "label_mismatch"


def test_html_200_and_server_errors_back_off(gse: GseServer) -> None:
    gse.override = lambda name: httpx.Response(
        200, headers={"content-type": "text/html"}, content=b"<html>"
    )
    w = window(gse)
    snap = w.snapshot(NOW)
    assert snap.error == "upstream_unavailable" and snap.latest is None
    n = len(gse.requests)
    w.snapshot(NOW + timedelta(seconds=35))  # backoff (>= 48 s with jitter) suppresses requests
    assert len(gse.requests) == n


def test_error_codes_never_contain_upstream_text(gse: GseServer) -> None:
    gse.override = lambda name: httpx.Response(
        200, headers={"content-type": "application/xml"}, content=b"<GSE><script>x</script></GSE>"
    )
    snap = window(gse).snapshot(NOW)
    assert snap.error == "schema_drift"


# ------------------------------------------------------------------------------------- forecast

RUN = utc(2026, 11, 14, 18)


def test_forecast_parses_recorded_response_for_three_sites() -> None:
    client = httpx.Client(transport=httpx.MockTransport(weather_handler([META])))
    data = core.fetch_forecast(client, now=RUN)
    assert data.run_time == RUN
    assert {r.site_id for r in data.rows} == {s.id for s in core.SITES}
    assert {r.height_m for r in data.rows} == {10, 80, 120, 180}
    assert all(r.speed_ms is None or 0 <= r.speed_ms <= 120 for r in data.rows)
    assert core.forecast_status(data, RUN + timedelta(hours=1)) == "fresh"
    assert core.forecast_status(data, RUN + timedelta(hours=13)) == "stale"  # old run
    assert core.forecast_status(data, RUN + timedelta(days=10)) == "unavailable"  # no coverage
    assert core.forecast_status(None, RUN) == "unavailable"


def test_forecast_refuses_run_change_during_fetch() -> None:
    newer = json.dumps({"last_run_initialisation_time": int(RUN.timestamp()) + 6 * 3600}).encode()
    client = httpx.Client(transport=httpx.MockTransport(weather_handler([META, newer])))
    with pytest.raises(core.openmeteo.OpenMeteoError):
        core.fetch_forecast(client)


def test_demo_uses_production_sources_and_rules() -> None:
    assert core.GSE_BASE_URL == "https://admin.gse.com.ge/storage/uploads/fact/"
    assert core.FRESH_WITHIN == timedelta(seconds=600)
    assert all(s.coordinates_verified for s in core.verified_sites())


def test_forecast_cache_keeps_last_good_and_backs_off_on_429() -> None:
    calls = {"n": 0, "fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["fail"] and request.url.path == "/v1/forecast":
            return httpx.Response(429)
        return weather_handler([META])(request)

    cache = core.ForecastCache(lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    t0 = RUN + timedelta(hours=1)
    data, err = cache.get(t0)
    assert data is not None and err is None
    n = calls["n"]
    cache.get(t0 + timedelta(minutes=5))  # within the refresh interval: no request
    assert calls["n"] == n
    calls["fail"] = True
    data2, err2 = cache.get(t0 + timedelta(minutes=16))
    assert data2 is data and err2 == "rate_limited"  # last good forecast kept
    n = calls["n"]
    cache.get(t0 + timedelta(minutes=18))  # backoff (5 min +-20%) still active: no request
    assert calls["n"] == n
    cache.get(t0 + timedelta(minutes=32))  # refresh due and backoff over: one retry
    cache.get(t0 + timedelta(minutes=33))  # just retried: no request
    assert calls["n"] - n == 2  # meta + forecast of the single retry


def test_error_codes_are_generic() -> None:
    req = httpx.Request("GET", "https://x")
    assert (
        core.error_code(httpx.HTTPStatusError("x", request=req, response=httpx.Response(429)))
        == "rate_limited"
    )
    assert (
        core.error_code(httpx.HTTPStatusError("x", request=req, response=httpx.Response(500)))
        == "upstream_unavailable"
    )
    assert core.error_code(core.openmeteo.OpenMeteoError("bad")) == "schema_drift"
    assert core.error_code(httpx.ConnectTimeout("t")) == "upstream_unavailable"
