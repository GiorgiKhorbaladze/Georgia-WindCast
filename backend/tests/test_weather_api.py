from datetime import datetime, timedelta

import pytest

from app.db import get_sessionmaker
from app.models import WeatherValue
from app.timeutil import utcnow

pytestmark = pytest.mark.db


def hour(t):
    return t.replace(minute=0, second=0, microsecond=0)


def add(site, product, model, run_at, valid_at, height, speed, direction=270.0):
    with get_sessionmaker()() as s, s.begin():
        s.add(
            WeatherValue(
                site_id=site,
                product=product,
                provider="open-meteo",
                model=model,
                run_ref=run_at.isoformat() if run_at else "era5",
                run_at=run_at,
                valid_at=valid_at,
                height_m=height,
                speed_ms=speed,
                direction_deg=direction,
                grid_latitude=42.0,
                grid_longitude=44.0,
                grid_elevation_m=800.0,
                retrieved_at=utcnow(),
            )
        )


def test_overview_unavailable_without_runs(migrated_db, client):
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "unavailable"
    assert body["unsupported_heights"] == [200]
    assert body["heights"] == {"forecast": [10, 80, 120, 180], "reanalysis": [10, 100]}
    assert all(n["speed_ms"] is None and n["measured"] is False for n in body["now"])
    assert len(body["sites"]) == 3


def test_overview_now_from_latest_run(migrated_db, client):
    now_h = hour(utcnow())
    old, new = now_h - timedelta(hours=12), now_h - timedelta(hours=6)
    add("ruisi", "forecast", "icon_global", old, now_h, 100 - 20, 5.0)
    add("ruisi", "forecast", "icon_global", new, now_h, 80, 7.5, 290)
    add("ruisi", "forecast", "icon_global", new, now_h + timedelta(hours=60), 80, 9.0)
    body = client.get("/api/v1/weather").json()
    # Only one site/height is stored, so the aggregate is never "fresh" (per-site coverage rule).
    assert body["forecast_state"] == "unavailable"
    assert body["forecast_reason"] == "incomplete_site_coverage"
    cur = next(n for n in body["now"] if n["site_id"] == "ruisi" and n["height_m"] == 80)
    assert cur["speed_ms"] == 7.5 and cur["direction_deg"] == 290
    assert body["forecast_model"] == "icon_global"


SITE_IDS = ("ruisi", "zemo-wind", "kartli-gori")
HEIGHTS = (10, 80, 120, 180)


def add_run(run, leads, sites=SITE_IDS, heights=HEIGHTS):
    """Bulk-add one forecast run covering the given sites/heights for the given lead hours."""
    with get_sessionmaker()() as s, s.begin():
        for site in sites:
            for h in heights:
                for lead in leads:
                    s.add(
                        WeatherValue(
                            site_id=site,
                            product="forecast",
                            provider="open-meteo",
                            model="icon_global",
                            run_ref=run.isoformat(),
                            run_at=run,
                            valid_at=run + timedelta(hours=lead),
                            height_m=h,
                            speed_ms=5.0,
                            direction_deg=270.0,
                            grid_latitude=42.0,
                            grid_longitude=44.0,
                            grid_elevation_m=800.0,
                            retrieved_at=utcnow(),
                        )
                    )


def test_expired_coverage_is_unavailable_never_negative(migrated_db, client):
    run = hour(utcnow()) - timedelta(days=2)
    add_run(run, range(0, 6))  # every site and height covered, but only in the past
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "unavailable"
    assert body["forecast_reason"] == "forecast_expired"
    assert body["forecast_horizon_end"] is None
    assert body["forecast_forward_hours"] == 0.0
    series = client.get("/api/v1/weather/sites/ruisi", params={"height": 10}).json()
    assert series["forecast"]["points"] == []


def test_partial_forward_coverage_is_stale(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, range(0, 12))  # every site/height, ends ~9 h ahead, below the 24 h minimum
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "stale" and body["forecast_reason"] == "partial_coverage"
    assert 0 < body["forecast_forward_hours"] < 24
    assert body["forecast_horizon_end"] is not None


def test_outdated_run_with_coverage_is_stale(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=20)  # older than the 12 h freshness window
    add_run(run, range(0, 100))
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "stale" and body["forecast_reason"] == "run_outdated"
    assert body["forecast_forward_hours"] == 72.0  # capped at the 72 h product horizon


def test_full_coverage_recent_run_is_fresh(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, range(0, 80))
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "fresh" and body["forecast_reason"] is None
    assert [c["forward_hours"] for c in body["site_coverage"]] == [72.0, 72.0, 72.0]


def test_missing_site_is_never_reported_fresh(migrated_db, client):
    """Review finding: one or two sites without coverage must not yield a Fresh aggregate."""
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, range(0, 80), sites=("ruisi",))
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "stale"
    assert body["forecast_reason"] == "incomplete_site_coverage"
    assert body["forecast_forward_hours"] == 0.0
    cov = {c["site_id"]: c["forward_hours"] for c in body["site_coverage"]}
    assert cov == {"ruisi": 72.0, "zemo-wind": 0.0, "kartli-gori": 0.0}


def test_site_missing_one_height_counts_as_uncovered(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, range(0, 80), sites=("ruisi", "kartli-gori"))
    add_run(run, range(0, 80), sites=("zemo-wind",), heights=(10, 80, 120))  # no 180 m
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "stale"
    assert body["forecast_reason"] == "incomplete_site_coverage"
    zemo = next(c for c in body["site_coverage"] if c["site_id"] == "zemo-wind")
    assert zemo["forward_hours"] == 0.0 and zemo["horizon_end"] is None


def test_shortest_site_sets_the_aggregate_horizon(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, range(0, 80), sites=("ruisi", "kartli-gori"))
    add_run(run, range(0, 15), sites=("zemo-wind",))  # ~11 h ahead only
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "stale" and body["forecast_reason"] == "partial_coverage"
    assert 0 < body["forecast_forward_hours"] < 24


def test_site_series_separates_history_forecast_and_reanalysis(migrated_db, client):
    now_h = hour(utcnow())
    r1, r2 = now_h - timedelta(hours=12), now_h - timedelta(hours=6)
    for lead in range(0, 24):
        add("zemo-wind", "forecast", "icon_global", r1, r1 + timedelta(hours=lead), 10, 1.0)
        add("zemo-wind", "forecast", "icon_global", r2, r2 + timedelta(hours=lead), 10, 2.0)
    add("zemo-wind", "reanalysis", "era5", None, now_h - timedelta(hours=8), 10, 4.0)
    body = client.get("/api/v1/weather/sites/zemo-wind", params={"height": 10}).json()
    hist = body["history"]["points"]
    # shortest-lead value wins: hours before r2 from run 1, hours from r2 on from run 2
    # shortest-lead value wins: 6 h from run 1, then run 2 up to and including the current hour
    assert [p["speed_ms"] for p in hist] == [1.0] * 6 + [2.0] * 7
    fc = body["forecast"]
    assert fc["run_at"].startswith(r2.isoformat()[:13])
    assert all(p["speed_ms"] == 2.0 for p in fc["points"])
    assert body["reanalysis"]["points"][0]["speed_ms"] == 4.0
    assert body["measured"] is False and body["unit"] == "m/s"
    assert body["history"]["supported"] and body["reanalysis"]["supported"]
    # Provenance: history combines two runs, so it claims no single run time; each point
    # carries its own run. The forecast is one run.
    assert body["history"]["provenance"] == "mixed_runs"
    assert body["history"]["run_at"] is None
    runs = {p["run_at"] for p in hist}
    assert len(runs) == 2
    assert all(p["run_at"].startswith(r1.isoformat()[:13]) for p in hist[:6])
    assert body["forecast"]["provenance"] == "single_run"
    assert {p["run_at"] for p in fc["points"]} == {fc["run_at"]}
    assert body["reanalysis"]["provenance"] == "reanalysis"
    assert body["reanalysis"]["points"][0]["run_at"] is None


def test_unsupported_height_is_explicit(migrated_db, client):
    body = client.get("/api/v1/weather/sites/ruisi", params={"height": 200}).json()
    for k in ("history", "forecast", "reanalysis"):
        assert body[k]["supported"] is False and body[k]["points"] == []
    b100 = client.get("/api/v1/weather/sites/ruisi", params={"height": 100}).json()
    assert b100["forecast"]["supported"] is False and b100["reanalysis"]["supported"] is True


@pytest.mark.parametrize(
    ("path", "params", "code"),
    [
        ("/api/v1/weather/sites/nowhere", {}, 404),
        ("/api/v1/weather/sites/ruisi", {"height": 50}, 422),
        (
            "/api/v1/weather/sites/ruisi",
            {"start": "2026-01-01T00:00:00Z", "end": "2026-03-01T00:00:00Z"},
            422,
        ),
    ],
)
def test_site_series_validation(migrated_db, client, path, params, code):
    assert client.get(path, params=params).status_code == code


def test_status_lists_weather_sources(migrated_db, weather_enabled, client):
    sources = {s["id"]: s["state"] for s in client.get("/api/v1/status").json()["sources"]}
    assert sources["open-meteo-forecast"] == "degraded"  # enabled, nothing fetched yet


def _cov(body):
    return {c["site_id"]: c for c in body["site_coverage"]}


def test_interior_gaps_end_contiguous_coverage(migrated_db, client):
    """Review finding: a distant point after missing hours is not usable coverage."""
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    # hours now-3 .. now+5 present, then a gap until now+20, then data to +80
    leads = [lead for lead in range(0, 84) if not (9 <= lead < 24)]
    add_run(run, leads)
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "stale"
    assert body["forecast_reason"] == "partial_coverage"
    assert body["forecast_forward_hours"] < 24
    c = _cov(body)["zemo-wind"]
    assert c["forward_hours"] < 24
    assert c["missing_hours"] == 15  # the interior gap is reported, not hidden
    assert c["last_valid_at"] is not None
    assert datetime.fromisoformat(c["last_valid_at"]) > now_h + timedelta(hours=70)


def test_single_far_point_is_not_coverage(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=1)
    add_run(run, [73])  # only a point ~72 h ahead at every height and site
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] != "fresh"
    assert body["forecast_reason"] == "incomplete_site_coverage"
    assert body["forecast_forward_hours"] == 0.0
    assert all(c["forward_hours"] == 0.0 and c["missing_hours"] > 60 for c in body["site_coverage"])


def test_missing_current_hour_means_no_contiguous_coverage(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, [lead for lead in range(0, 80) if lead != 3])  # lead 3 == current hour
    body = client.get("/api/v1/weather").json()
    assert body["forecast_reason"] == "incomplete_site_coverage"
    assert all(c["forward_hours"] == 0.0 for c in body["site_coverage"])


def test_gap_at_one_height_breaks_contiguity(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, range(0, 80), heights=(10, 80, 120))
    add_run(run, [lead for lead in range(0, 80) if lead != 13], heights=(180,))  # now+10 missing
    body = client.get("/api/v1/weather").json()
    assert body["forecast_reason"] == "partial_coverage"
    c = _cov(body)["ruisi"]
    assert c["forward_hours"] <= 10.0 and c["missing_hours"] == 1


def test_contiguous_full_coverage_reports_no_missing_hours(migrated_db, client):
    now_h = hour(utcnow())
    run = now_h - timedelta(hours=3)
    add_run(run, range(0, 80))
    body = client.get("/api/v1/weather").json()
    assert body["forecast_state"] == "fresh"
    assert all(c["missing_hours"] == 0 for c in body["site_coverage"])
