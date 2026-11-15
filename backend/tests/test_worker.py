import threading

import pytest
from sqlalchemy import create_engine, text

from app import worker


@pytest.mark.db
def test_worker_loop_records_heartbeat_and_stops(migrated_db, monkeypatch):
    monkeypatch.setenv("WINDCAST_WORKER_HEARTBEAT_SECONDS", "1")
    stop = threading.Event()
    t = threading.Thread(target=worker.run, args=(stop,))
    t.start()
    try:
        engine = create_engine(migrated_db)
        for _ in range(50):
            with engine.connect() as conn:
                if conn.execute(text("SELECT count(*) FROM worker_heartbeat")).scalar():
                    break
            stop.wait(0.1)
        else:
            pytest.fail("worker did not record a heartbeat")
        engine.dispose()
    finally:
        stop.set()
        t.join(timeout=5)
    assert not t.is_alive()


def test_worker_survives_database_outage(monkeypatch):
    """With an unreachable DB the loop logs and keeps going until stopped."""
    calls = []
    stop = threading.Event()

    def failing(*_a):
        calls.append(1)
        if len(calls) >= 2:
            stop.set()
        raise RuntimeError("db down")

    monkeypatch.setenv("WINDCAST_WORKER_HEARTBEAT_SECONDS", "1")
    monkeypatch.setattr(worker, "record_heartbeat", failing)
    worker.run(stop)
    assert len(calls) == 2


@pytest.mark.db
def test_healthcheck_reflects_heartbeat(migrated_db, monkeypatch):
    from datetime import timedelta

    from app import healthcheck
    from app.timeutil import utcnow

    name = worker.default_worker_name()
    assert healthcheck.main() == 1  # no heartbeat yet
    worker.record_heartbeat(name, utcnow())
    assert healthcheck.main() == 0
    monkeypatch.setattr(healthcheck, "utcnow", lambda: utcnow() + timedelta(hours=1))
    assert healthcheck.main() == 1  # stale


def test_healthcheck_fails_closed_without_database(monkeypatch):
    from app import healthcheck
    from app.config import get_settings
    from app.db import get_engine, get_sessionmaker

    monkeypatch.setenv("WINDCAST_DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:1/none")
    for f in (get_settings, get_engine, get_sessionmaker):
        f.cache_clear()
    assert healthcheck.main() == 1


@pytest.mark.db
def test_worker_runs_enabled_weather_and_gse_jobs(migrated_db, monkeypatch):
    """Regression: the weather job must actually be scheduled by the worker loop."""
    calls: list[str] = []
    stop = threading.Event()

    def fake_weather(job):
        calls.append("weather")
        stop.set()

    monkeypatch.setenv("WINDCAST_WEATHER_INGESTION_ENABLED", "true")
    monkeypatch.setenv("WINDCAST_GSE_INGESTION_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(worker, "run_gse_tick", lambda job: calls.append("gse"))
    monkeypatch.setattr(worker, "run_weather_tick", fake_weather)
    worker.run(stop)
    assert calls == ["gse", "weather"]


@pytest.mark.db
def test_run_weather_tick_survives_job_errors(migrated_db):
    class Boom:
        def tick_forecast(self, session):
            raise RuntimeError("forecast boom")

        def tick_reanalysis(self, session):
            raise RuntimeError("reanalysis boom")

        def prune(self, session):
            raise RuntimeError("prune boom")

    worker.run_weather_tick(Boom())  # must not raise


def test_heartbeat_touches_liveness_file_only_after_commit(migrated_db, monkeypatch, tmp_path):
    """The container healthcheck reads this file's age instead of starting Python (PR #19 ARM64)."""
    from datetime import UTC, datetime

    from app import identity, worker

    alive = tmp_path / "alive"
    monkeypatch.setenv("WINDCAST_WORKER_ALIVE_FILE", str(alive))
    assert identity.alive_age_seconds() is None
    worker.record_heartbeat("worker@test", datetime.now(UTC))
    age = identity.alive_age_seconds()
    assert age is not None and 0 <= age < 5


def test_liveness_file_not_touched_when_heartbeat_fails(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    import pytest

    from app import identity, worker
    from app.config import get_settings
    from app.db import get_engine, get_sessionmaker

    alive = tmp_path / "alive"
    monkeypatch.setenv("WINDCAST_WORKER_ALIVE_FILE", str(alive))
    monkeypatch.setenv(
        "WINDCAST_DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"
    )
    for f in (get_settings, get_engine, get_sessionmaker):
        f.cache_clear()
    with pytest.raises(Exception):  # noqa: B017 - any DB error
        worker.record_heartbeat("worker@test", datetime.now(UTC))
    assert identity.alive_age_seconds() is None


def test_healthcheck_module_stays_lightweight():
    """The DB healthcheck must not import the ingestion stack (slow under emulation)."""
    import subprocess
    import sys

    code = (
        "import sys, app.healthcheck; "
        "bad = [m for m in ('app.worker', 'app.ingestion.gse_job', 'httpx') if m in sys.modules]; "
        "sys.exit(1 if bad else 0)"
    )
    # Fixed argv, no shell, no external input.
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0  # noqa: S603
