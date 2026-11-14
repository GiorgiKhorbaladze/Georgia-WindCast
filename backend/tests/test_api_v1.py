from datetime import timedelta

import pytest

from app.timeutil import utcnow
from app.worker import record_heartbeat


def test_generation_latest_reports_unavailable_without_value(client):
    r = client.get("/api/v1/generation/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["freshness"] == "unavailable"
    assert body["value_mw"] is None
    assert body["scope"] == "national_aggregate"
    assert body["unit"] == "MW"
    assert body["source"]["url"] == "https://www.gse.com.ge"


def test_no_per_site_generation_in_contract(client):
    schema = client.get("/api/openapi.json").json()["components"]["schemas"]
    assert "value_mw" not in schema["SiteSummary"]["properties"]
    for name, definition in schema.items():
        if name != "GenerationLatest":
            assert "value_mw" not in definition.get("properties", {}), name


@pytest.mark.db
def test_status_worker_never_seen(migrated_db, client):
    body = client.get("/api/v1/status").json()
    assert body["worker"] == {"state": "never_seen", "last_seen_at": None}
    assert len(body["sites"]) == 3
    assert all(not s["coordinates_verified"] and s["latitude"] is None for s in body["sites"])
    assert {s["id"]: s["state"] for s in body["sources"]} == {
        "gse": "not_configured",
        "open-meteo": "not_configured",
    }


@pytest.mark.db
def test_status_worker_running_then_stale(migrated_db, client, monkeypatch):
    record_heartbeat("worker@test", utcnow())
    assert client.get("/api/v1/status").json()["worker"]["state"] == "running"

    future = utcnow() + timedelta(hours=1)
    monkeypatch.setattr("app.api.v1.utcnow", lambda: future)
    assert client.get("/api/v1/status").json()["worker"]["state"] == "stale"


@pytest.mark.db
def test_heartbeat_is_idempotent_upsert(migrated_db):
    from sqlalchemy import create_engine, text

    t0 = utcnow()
    record_heartbeat("worker@test", t0)
    record_heartbeat("worker@test", t0)
    engine = create_engine(migrated_db)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM worker_heartbeat")).scalar() == 1
    engine.dispose()
