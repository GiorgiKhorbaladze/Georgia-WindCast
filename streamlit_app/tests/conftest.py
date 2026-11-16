"""Shared helpers: recorded GSE/Open-Meteo payloads from backend/tests/fixtures, served offline."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "streamlit_app"))
FIX = ROOT / "backend" / "tests" / "fixtures"
REAL_ACT = (FIX / "gse" / "real_act_15112026_0009.xml").read_bytes()  # 73.599297 MW, ACT
REAL_NRE = (FIX / "gse" / "real_nre_15112026_0003.xml").read_bytes()  # 91.333824 MW, NRE
FORECAST = (FIX / "openmeteo" / "real_forecast_icon_global_3sites.json").read_bytes()
META = (FIX / "openmeteo" / "real_meta_dwd_icon_before.json").read_bytes()  # run 2026-11-14 18Z

NAME = re.compile(r"GSE_EXPORT_NEW_PERIOD_03M_(\d\d)(\d\d)(\d{4})_(\d\d)(\d\d)\.XML$")


def relabel(base: bytes, local: str) -> bytes:
    """Recorded file with another Export Time (labelled derivation, never a new value)."""
    old = re.search(rb"Time='[^']+'", base)
    assert old is not None
    return base.replace(old.group(0), f"Time='{local}'".encode(), 1)


class GseServer:
    """Answers GSE file requests: recorded content relabelled to the requested period."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.missing: set[str] = set()  # local "HH:MM" that answer 404
        self.base = REAL_ACT
        self.override: Callable[[str], httpx.Response] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        self.requests.append(name)
        if self.override is not None:
            return self.override(name)
        m = NAME.search(name)
        assert m, name
        dd, mm, yyyy, hh, mi = m.groups()
        if f"{hh}:{mi}" in self.missing:
            return httpx.Response(404, headers={"content-type": "text/html"}, content=b"nf")
        body = relabel(self.base, f"{dd}.{mm}.{yyyy} {hh}:{mi}:00")
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def gse() -> GseServer:
    return GseServer()


def weather_handler(metas: list[bytes]) -> Callable[[httpx.Request], httpx.Response]:
    queue = list(metas)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("meta.json"):
            return httpx.Response(200, content=queue.pop(0) if len(queue) > 1 else queue[0])
        assert request.url.path == "/v1/forecast"
        return httpx.Response(200, content=FORECAST)

    return handler


def utc(*args: int) -> datetime:
    from datetime import UTC

    return datetime(*args, tzinfo=UTC)
