"""Test configuration.

Database tests run against a real PostgreSQL instance named by TEST_DATABASE_URL (CI provides
a service container). They are skipped, loudly, when it is not set. No test touches any
external network service.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.migrations import alembic_config

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
# CI sets this so that database tests can never be skipped silently.
REQUIRE_DB = os.environ.get("WINDCAST_REQUIRE_DB_TESTS") == "1"


def _require_db() -> None:
    if not TEST_DATABASE_URL:
        if REQUIRE_DB:
            pytest.fail("WINDCAST_REQUIRE_DB_TESTS=1 but TEST_DATABASE_URL is not set")
        pytest.skip("TEST_DATABASE_URL not set")


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("WINDCAST_APP_ENV", "test")
    if TEST_DATABASE_URL:
        monkeypatch.setenv("WINDCAST_DATABASE_URL", TEST_DATABASE_URL)
    else:
        # An unroutable URL guarantees no accidental use of a developer database.
        monkeypatch.setenv(
            "WINDCAST_DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"
        )
    _clear_caches()
    yield
    _clear_caches()


def _reset_schema(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _alembic_cfg():
    cfg = alembic_config()
    cfg.attributes["configure_logger"] = False
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    return cfg


@pytest.fixture
def migrated_db() -> Iterator[str]:
    _require_db()
    assert TEST_DATABASE_URL
    _reset_schema(TEST_DATABASE_URL)
    command.upgrade(_alembic_cfg(), "head")
    yield TEST_DATABASE_URL
    get_engine().dispose()


@pytest.fixture
def empty_db() -> Iterator[str]:
    _require_db()
    assert TEST_DATABASE_URL
    _reset_schema(TEST_DATABASE_URL)
    yield TEST_DATABASE_URL
    get_engine().dispose()


@pytest.fixture
def alembic_cfg():
    return _alembic_cfg()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
