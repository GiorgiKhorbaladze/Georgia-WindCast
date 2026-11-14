"""Scheduled ingestion worker.

Runs the heartbeat and, when enabled, the GSE national wind ingestion job (issue #3).
Each job runs in its own transaction; an exception in one job never stops the loop.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from datetime import datetime
from types import FrameType

from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import get_sessionmaker
from app.ingestion.gse_job import GseIngestionJob, build_client
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


def default_worker_name() -> str:
    return f"worker@{socket.gethostname()}"[:64]


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

    next_heartbeat = next_gse = time.monotonic()
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_heartbeat:
            try:
                record_heartbeat(worker_name, started_at)
            except Exception:  # keep the worker alive across transient DB outages
                log.exception("heartbeat failed")
            next_heartbeat = now + settings.worker_heartbeat_seconds
        if gse_job is not None and now >= next_gse:
            run_gse_tick(gse_job)
            next_gse = now + settings.gse_poll_seconds
        stop.wait(
            max(
                0.0, min(next_heartbeat, next_gse if gse_job else next_heartbeat) - time.monotonic()
            )
        )
    if gse_job is not None:
        gse_job.client.close()
    log.info("worker stopped")


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
