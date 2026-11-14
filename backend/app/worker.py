"""Scheduled ingestion worker.

In the foundation stage the worker only records a heartbeat so that liveness can be
observed end to end. Source jobs (GSE, Open-Meteo) are added under issues #3 and #4.
"""

from __future__ import annotations

import logging
import signal
import socket
import threading
from datetime import datetime
from types import FrameType

from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import get_sessionmaker
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
    log.info("worker %s starting (env=%s)", worker_name, settings.app_env.value)
    while not stop.is_set():
        try:
            record_heartbeat(worker_name, started_at)
        except Exception:  # keep the worker alive across transient DB outages
            log.exception("heartbeat failed")
        stop.wait(settings.worker_heartbeat_seconds)
    log.info("worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()
