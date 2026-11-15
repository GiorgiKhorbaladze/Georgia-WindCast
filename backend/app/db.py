"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# Fail fast instead of queueing for 30 s when the pool is busy, and let PostgreSQL end any
# transaction left idle (defence in depth against a leaked session) or any runaway statement.
POOL_TIMEOUT_SECONDS = 5
IDLE_IN_TRANSACTION_TIMEOUT_MS = 30_000
STATEMENT_TIMEOUT_MS = 15_000


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_timeout=POOL_TIMEOUT_SECONDS,
        connect_args={
            "options": (
                f"-c idle_in_transaction_session_timeout={IDLE_IN_TRANSACTION_TIMEOUT_MS}"
                f" -c statement_timeout={STATEMENT_TIMEOUT_MS}"
            )
        },
        future=True,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session opened and closed in the calling thread.

    API endpoints are synchronous and run in worker threads. They use this context manager in
    their body instead of a request-scoped ``yield`` dependency: when a client disconnects
    mid-request, the dependency's teardown could be skipped or run on another thread, leaving the
    connection "idle in transaction" until the pool was exhausted and the API hung (found by the
    issue #18 load test; regression test: tests/test_connection_safety.py).
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
