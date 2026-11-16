"""Every test runs offline with a fixed clock: no upstream, no data-branch request."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "streamlit_cloud"
# Backend first, so streamlit_cloud/app.py never shadows the backend `app` package.
sys.path[:0] = [str(ROOT / "backend"), str(HERE)]

CLOCK = datetime(2026, 11, 14, 20, 11, tzinfo=UTC)


@pytest.fixture(autouse=True)
def offline_history(request):
    """Default: the durable store is empty and the clock is fixed. Tests may override both."""
    import streamlit as st

    st.cache_resource.clear()
    if request.node.get_closest_marker("real_history"):  # tests of HistoryReader itself
        with patch("data.utcnow", return_value=CLOCK) as clock:
            yield clock
        return
    durable = getattr(request, "param", [])
    with (
        patch("data.utcnow", return_value=CLOCK) as clock,
        patch("history.HistoryReader.records", side_effect=lambda s, e, n: [r for r in durable if s <= r.period_label_utc <= e]),
        patch("history.HistoryReader.status", return_value=None),
        patch("history.HistoryReader.weather", return_value=(None, None)),
    ):
        yield clock


def pytest_configure(config):
    config.addinivalue_line("markers", "real_history: do not stub HistoryReader")
