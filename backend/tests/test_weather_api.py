from datetime import timedelta

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
    assert body["forecast_state"] == "fresh"
    cur = next(n for n in body["now"] if n["site_id"] == "ruisi" and n["height_m"] == 80)
    assert cur["speed_ms"] == 7.5 and cur["direction_deg"] == 290
    assert body["forecast_model"] == "icon_global"


def test_overview_stale_run(migrated_db, client):
    run = hour(utcnow()) - timedelta(days=2)
    add("ruisi", "forecast", "icon_global", run, run, 10, 3.0)
    assert client.get("/api/v1/weather").json()["forecast_state"] == "stale"


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
