"""Health and startup tests."""

import pytest
from sqlalchemy import create_engine, text

from alembic import command


def test_liveness_does_not_need_database(client):
    # conftest points the app at an unroutable database when TEST_DATABASE_URL is absent;
    # liveness must still succeed because it never touches the database.
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "windcast-api"


def test_openapi_is_served(client):
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    assert "/api/health/ready" in r.json()["paths"]


@pytest.mark.db
def test_readiness_ok_when_migrated(migrated_db, client):
    r = client.get("/api/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["migration_revision"] == body["migration_head"] == "0001_foundation"


@pytest.mark.db
def test_readiness_503_when_schema_missing(empty_db, client):
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"


@pytest.mark.db
def test_readiness_503_when_behind_head(migrated_db, alembic_cfg, client):
    command.downgrade(alembic_cfg, "base")
    engine = create_engine(migrated_db)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32))"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0000_older')"))
    engine.dispose()
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json()["detail"] == "database schema is not at the migration head"


def test_readiness_503_when_database_unreachable(monkeypatch, client):
    from app.config import get_settings
    from app.db import get_engine, get_sessionmaker

    monkeypatch.setenv(
        "WINDCAST_DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"
    )
    for f in (get_settings, get_engine, get_sessionmaker):
        f.cache_clear()
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json()["database"] == "error"
