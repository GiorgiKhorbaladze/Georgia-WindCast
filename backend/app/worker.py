"""Scheduled ingestion worker.

Runs the heartbeat and, when enabled, the GSE national wind ingestion job (issue #3).
Each job runs in its own transaction; an exception in one job never stops the loop.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime
from types import FrameType

from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import get_sessionmaker
from app.identity import alive_file, default_worker_name, touch_alive
from app.ingestion.gse_job import GseIngestionJob, build_client
from app.ingestion.weather_job import WeatherIngestionJob, build_weather_client
from app.models import WorkerHeartbeat
from app.timeutil import utcnow
from app.version import __version__

log = logging.getLogger("windcast.worker")


def record_heartbeat(worker_name: str, started_at: datetime) -> None:
    now = utcnow()
    stmt = insert(WorkerHeartbeat).values(
        worker_name=worker_name, started_at=started_at, last_seen_at=now, version=__version__
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[WorkerHeartbeat.worker_name],
        set_={"started_at": started_at, "last_seen_at": now, "version": __version__},
    )
    with get_sessionmaker()() as session, session.begin():
        session.execute(stmt)
    # Only after the commit: the container healthcheck reads this file's age (cheap, no Python).
    try:
        touch_alive()
    except OSError:
        log.warning("could not update the liveness file %s", alive_file(), exc_info=True)


def run(stop: threading.Event | None = None) -> None:
    settings = get_settings()
    stop = stop or threading.Event()
    worker_name = default_worker_name()

    def _handle(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %s, shutting down", signum)
        stop.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)

    started_at = utcnow()
    log.info(
        "worker %s starting (env=%s, gse_ingestion=%s, weather_ingestion=%s)",
        worker_name,
        settings.app_env.value,
        settings.gse_ingestion_enabled,
        settings.weather_ingestion_enabled,
    )
    gse_job: GseIngestionJob | None = None
    if settings.gse_ingestion_enabled:
        gse_job = GseIngestionJob(settings, build_client(settings))
    weather_job: WeatherIngestionJob | None = None
    if settings.weather_ingestion_enabled:
        weather_job = WeatherIngestionJob(settings, build_weather_client(settings))

    t0 = time.monotonic()
    due = {"heartbeat": t0, "gse": t0, "weather": t0}
    while not stop.is_set():
        now = time.monotonic()
        if now >= due["heartbeat"]:
            try:
                record_heartbeat(worker_name, started_at)
            except Exception:  # keep the worker alive across transient DB outages
                log.exception("heartbeat failed")
            due["heartbeat"] = now + settings.worker_heartbeat_seconds
        if gse_job is not None and now >= due["gse"]:
            run_gse_tick(gse_job)
            due["gse"] = now + settings.gse_poll_seconds
        if weather_job is not None and now >= due["weather"]:
            run_weather_tick(weather_job)
            due["weather"] = now + settings.weather_poll_seconds
        upcoming = [due["heartbeat"]]
        if gse_job is not None:
            upcoming.append(due["gse"])
        if weather_job is not None:
            upcoming.append(due["weather"])
        stop.wait(max(0.0, min(upcoming) - time.monotonic()))
    for job in (gse_job, weather_job):
        if job is not None:
            job.client.close()
    log.info("worker stopped")


def run_weather_tick(job: WeatherIngestionJob) -> None:
    """Forecast, reanalysis and retention, each in its own transaction."""
    for name, step in (("forecast", job.tick_forecast), ("reanalysis", job.tick_reanalysis)):
        try:
            with get_sessionmaker()() as session, session.begin():
                report = step(session)
            if report.requested or report.failure:
                log.info(
                    "weather %s: requested=%d stored=%d skipped=%s failure=%s run=%s",
                    name,
                    report.requested,
                    report.stored,
                    report.skipped,
                    report.failure,
                    report.run_at,
                )
        except Exception:
            log.exception("weather %s tick failed", name)
    try:
        with get_sessionmaker()() as session, session.begin():
            pruned = job.prune(session)
        if pruned:
            log.info("weather retention: pruned %d long-lead forecast values", pruned)
    except Exception:
        log.exception("weather retention failed")


def run_gse_tick(job: GseIngestionJob) -> None:
    try:
        with get_sessionmaker()() as session, session.begin():
            report = job.tick(session)
        if report.requested or report.failure:
            log.info(
                "gse tick: requested=%d stored=%d duplicates=%d not_published=%d failure=%s",
                report.requested,
                report.stored,
                report.duplicates,
                report.not_published,
                report.failure,
            )
    except Exception:
        log.exception("gse tick failed")


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("WINDCAST_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run()
