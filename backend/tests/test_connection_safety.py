"""Regression: cancelled requests must not leak database connections (issue #18 load test).

Under load the frontend aborts slow backend calls after 6 s. With a request-scoped ``yield``
session dependency, cancelled requests left their sessions "idle in transaction"; after 15 such
requests the pool was exhausted and every endpoint, including /api/health, hung until restart.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from sqlalchemy import event

from app.db import get_engine

ENDPOINTS = [
    "/api/v1/generation/latest",
    "/api/v1/generation/history",
    "/api/v1/status",
    "/api/v1/weather",
    "/api/v1/weather/sites/ruisi?height=120",
    "/api/health/ready",
]


@pytest.fixture
def live_server(migrated_db: str) -> Iterator[str]:
    """The real ASGI server (uvicorn), as in production, on a free local port."""
    from app.main import create_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_aborted_requests_release_their_connections(live_server: str) -> None:
    engine = get_engine()
    pool = engine.pool
    capacity = pool.size() + pool._max_overflow  # type: ignore[attr-defined]

    # Make every statement slow, so connections are checked out when clients give up (as under
    # real load, where requests queued behind each other).
    def slow(*_args: object) -> None:
        time.sleep(0.2)

    event.listen(engine, "before_cursor_execute", slow)

    async def burst() -> None:
        # Clients that give up almost immediately, like the frontend's fetch timeout under load.
        async with httpx.AsyncClient(base_url=live_server, timeout=0.3) as client:

            async def aborted(path: str) -> None:
                try:
                    await client.get(path)
                except httpx.HTTPError:
                    pass

            await asyncio.gather(
                *(aborted(ENDPOINTS[i % len(ENDPOINTS)]) for i in range(capacity * 6))
            )

    asyncio.run(burst())

    # Worker threads finish the abandoned endpoints; every connection must come back.
    deadline = time.monotonic() + 30
    while pool.checkedout() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert pool.checkedout() == 0, f"{pool.checkedout()} connections leaked"

    event.remove(engine, "before_cursor_execute", slow)
    # And the service still answers normally.
    with httpx.Client(base_url=live_server, timeout=10) as client:
        for path in ENDPOINTS:
            res = client.get(path)
            assert res.status_code in (200, 503), (path, res.status_code)


def test_pool_fails_fast_and_server_reaps_idle_transactions(migrated_db: str) -> None:
    engine = get_engine()
    assert engine.pool.timeout() <= 10  # type: ignore[attr-defined]
    with engine.connect() as conn:
        idle = conn.exec_driver_sql("SHOW idle_in_transaction_session_timeout").scalar()
        stmt = conn.exec_driver_sql("SHOW statement_timeout").scalar()
    assert idle not in (None, "0"), idle
    assert stmt not in (None, "0"), stmt
