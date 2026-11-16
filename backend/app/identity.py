"""Lightweight worker identity and liveness-file helpers.

Imported by the container healthcheck path, so it must stay cheap: no SQLAlchemy, no HTTP stack.
Under QEMU emulation a healthcheck that imported the worker module took ~22 s per probe (PR #19
ARM64 job), longer than its timeout.
"""

from __future__ import annotations

import os
import socket
import time

# Touched after every successful database heartbeat. The container healthcheck tests its age with
# the shell (compose.yaml), so a probe never starts Python.
# Inside the container only (private filesystem); the file holds no data, just an mtime.
DEFAULT_ALIVE_FILE = "/tmp/windcast-worker.alive"  # noqa: S108


def default_worker_name() -> str:
    return f"worker@{socket.gethostname()}"[:64]


def alive_file() -> str:
    return os.environ.get("WINDCAST_WORKER_ALIVE_FILE", DEFAULT_ALIVE_FILE)


def touch_alive(path: str | None = None) -> None:
    """Mark the worker alive (mtime = now). Called only after the DB heartbeat committed."""
    target = path or alive_file()
    with open(target, "a", encoding="utf-8"):
        pass
    os.utime(target, None)


def alive_age_seconds(path: str | None = None, now: float | None = None) -> float | None:
    try:
        mtime = os.stat(path or alive_file()).st_mtime
    except FileNotFoundError:
        return None
    return (now if now is not None else time.time()) - mtime
