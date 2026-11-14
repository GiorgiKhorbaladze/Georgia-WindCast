from datetime import UTC, datetime

import pytest

from app.ingestion.gse_job import due_labels, floor_period
from app.ingestion.gse_parser import (
    GseSchemaError,
    GseValueError,
    export_file_name,
    parse_export_time,
    parse_wind_export,
)
from tests.gse_fixtures import REAL_ACT, REAL_NRE, mutate, with_wind_value


def test_real_export_act():
    r = parse_wind_export(REAL_ACT)
    assert r.value_mw == pytest.approx(73.599297)
    assert r.quality == "ACT"
    assert r.period_label_local == "15.11.2026 00:09:00"
    # Asia/Tbilisi is UTC+4 all year: 00:09 local on 15 Nov is 20:09 UTC on 14 Nov.
    assert r.period_label_utc == datetime(2026, 11, 14, 20, 9, tzinfo=UTC)


def test_real_export_nre_quality_is_preserved_not_judged():
    r = parse_wind_export(REAL_NRE)
    assert r.quality == "NRE"
    assert r.value_mw == pytest.approx(91.333824)


@pytest.mark.parametrize(
    ("raw", "expected"), [("0.000000", 0.0), ("-0.000000", 0.0), ("-1.250000", -1.25)]
)
def test_zero_and_small_negative_values_are_real_readings(raw, expected):
    r = parse_wind_export(with_wind_value(raw))
    assert r.value_mw == expected
    assert str(r.value_mw) != "-0.0"


@pytest.mark.parametrize("raw", ["", "abc", "nan", "NaN", "inf", "-inf", "1e999"])
def test_invalid_values_rejected(raw):
    with pytest.raises(GseValueError):
        parse_wind_export(with_wind_value(raw))


@pytest.mark.parametrize("raw", ["5000.0", "-500.0"])
def test_implausible_values_rejected(raw):
    with pytest.raises(GseValueError, match="implausible"):
        parse_wind_export(with_wind_value(raw))


SCHEMA_DRIFT = {
    "missing wind block": (b"TOTAL WIND PLANTS", b"TOTAL BREEZE PLANTS"),
    "wrong period": (b"Period='03M'", b"Period='01M'"),
    "bad time": (b"Time='15.11.2026 00:09:00'", b"Time='2026-11-15T00:09:00'"),
    "missing time": (b"Time='15.11.2026 00:09:00' ", b""),
    "renamed input": (b"IN='MvAvr03m' VALUE='73.599297'", b"IN='MvAvr01m' VALUE='73.599297'"),
    "empty quality": (
        b"QUALITY='ACT'/>\n</BLOCK_AREA>\n<BLOCK_AREA Name='TOTAL SUN",
        b"QUALITY=' '/>\n</BLOCK_AREA>\n<BLOCK_AREA Name='TOTAL SUN",
    ),
    "missing value": (b"VALUE='73.599297' ", b""),
    "root renamed": (b"<GSE DTD_Version='1'>", b"<XGSE DTD_Version='1'>"),
}


@pytest.mark.parametrize("case", SCHEMA_DRIFT)
def test_schema_drift_rejected(case):
    old, new = SCHEMA_DRIFT[case]
    payload = mutate(old, new)
    if case == "root renamed":
        payload = payload.replace(b"</GSE>", b"</XGSE>")
    with pytest.raises(GseSchemaError):
        parse_wind_export(payload)


def test_duplicate_wind_entries_are_refused_not_summed():
    ta = (
        b"<TA B1='AllGeorg' B2='WindPP' B3=' ' EL='P' IN='MvAvr03m' "
        b"VALUE='73.599297' QUALITY='ACT'/>"
    )
    payload = mutate(ta, ta + b"\n" + ta)
    with pytest.raises(GseSchemaError, match="found 2"):
        parse_wind_export(payload)


def test_html_page_is_not_data():
    html = b"<!doctype html><html><head><title>gse</title></head><body></body></html>"
    with pytest.raises(GseSchemaError):
        parse_wind_export(html)


def test_entity_expansion_is_forbidden():
    bomb = (
        b"<?xml version='1.0'?><!DOCTYPE GSE [<!ENTITY a 'aaaaaaaaaa'>"
        b"<!ENTITY b '&a;&a;&a;&a;&a;&a;&a;&a;'>]><GSE>&b;</GSE>"
    )
    with pytest.raises(GseSchemaError, match="forbidden"):
        parse_wind_export(bomb)


def test_truncated_payload():
    with pytest.raises(GseSchemaError):
        parse_wind_export(REAL_ACT[: len(REAL_ACT) // 2])


def test_export_file_name_uses_tbilisi_time_across_midnight():
    assert export_file_name(datetime(2026, 11, 14, 20, 9, tzinfo=UTC)) == (
        "GSE_EXPORT_NEW_PERIOD_03M_15112026_0009.XML"
    )


def test_parse_export_time_roundtrip():
    t = parse_export_time("01.01.2027 03:57:00")
    assert t == datetime(2026, 12, 31, 23, 57, tzinfo=UTC)


def test_floor_and_due_labels():
    now = datetime(2026, 11, 14, 20, 11, 30, tzinfo=UTC)
    assert floor_period(now) == datetime(2026, 11, 14, 20, 9, tzinfo=UTC)
    from datetime import timedelta

    labels = due_labels(now, timedelta(seconds=75), 3)
    assert labels == [
        datetime(2026, 11, 14, 20, 9, tzinfo=UTC),
        datetime(2026, 11, 14, 20, 6, tzinfo=UTC),
        datetime(2026, 11, 14, 20, 3, tzinfo=UTC),
    ]
    # Before the publication lag passes, the current period is not yet due.
    assert due_labels(datetime(2026, 11, 14, 20, 10, 0, tzinfo=UTC), timedelta(seconds=75), 1) == [
        datetime(2026, 11, 14, 20, 6, tzinfo=UTC)
    ]
