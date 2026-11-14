"""Recorded GSE exports and labelled mutations of them.

``real_*.xml`` are unmodified public files fetched from admin.gse.com.ge on 2026-11-14 (UTC).
Every other variant is produced here by an explicit text substitution on a real file, so a
test can never mistake synthetic content for a recorded one.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "gse"
REAL_ACT = (FIXTURES / "real_act_15112026_0009.xml").read_bytes()  # 73.599297 MW, ACT
REAL_NRE = (FIXTURES / "real_nre_15112026_0003.xml").read_bytes()  # 91.333824 MW, NRE
REAL_ACT_NAME = "GSE_EXPORT_NEW_PERIOD_03M_15112026_0009.XML"
REAL_NRE_NAME = "GSE_EXPORT_NEW_PERIOD_03M_15112026_0003.XML"
WIND_VALUE = b"VALUE='73.599297' QUALITY='ACT'"


def mutate(old: bytes, new: bytes, base: bytes = REAL_ACT) -> bytes:
    assert base.count(old) == 1, f"mutation target {old!r} must occur exactly once"
    return base.replace(old, new)


def with_wind_value(value: str) -> bytes:
    return mutate(WIND_VALUE, f"VALUE='{value}' QUALITY='ACT'".encode())


def relabel(local_time: str, base: bytes = REAL_ACT) -> bytes:
    """Same content with another Export Time, e.g. '15.11.2026 00:12:00'."""
    old = b"Time='15.11.2026 00:09:00'" if base is REAL_ACT else b"Time='15.11.2026 00:03:00'"
    return mutate(old, f"Time='{local_time}'".encode(), base)
