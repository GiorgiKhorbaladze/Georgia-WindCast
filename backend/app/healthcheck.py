"""Database-level worker check: exit 0 only if this host's heartbeat row is recent.

Usage: python -m app.healthcheck   (diagnostics; the container healthcheck uses the cheaper
liveness-file test in compose.yaml, see app/identity.py)
"""

from __future__ import annotations

import sys
from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.identity import default_worker_name
from app.models import WorkerHeartbeat
from app.timeutil import utcnow


def worker_is_healthy(worker_name: str) -> bool:
    settings = get_settings()
    with get_sessionmaker()() as session:
        last_seen = session.execute(
            select(WorkerHeartbeat.last_seen_at).where(WorkerHeartbeat.worker_name == worker_name)
        ).scalar()
    if last_seen is None:
        return False
    return utcnow() - last_seen <= timedelta(seconds=settings.worker_stale_after_seconds)


def main() -> int:
    try:
        return 0 if worker_is_healthy(default_worker_name()) else 1
    except Exception as exc:
        print(f"healthcheck error: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
