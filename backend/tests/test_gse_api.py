from datetime import UTC, datetime, timedelta

import pytest

from app.db import get_sessionmaker
from app.models import GenerationReading, SourceStatusRecord
from app.timeutil import utcnow

pytestmark = pytest.mark.db


def add(t: datetime, value=50.0, quality="ACT"):
    with get_sessionmaker()() as s, s.begin():
        s.add(
            GenerationReading(
                source="gse",
                metric="wind_total",
                period_label_at=t,
                period_label_local="x",
                value_mw=value,
                quality=quality,
                source_url="https://example.invalid/f.XML",
                payload_sha256="0" * 64,
                parser_version="test",
                retrieved_at=t + timedelta(seconds=80),
            )
        )


def set_status(**kw):
    with get_sessionmaker()() as s, s.begin():
        row = s.get(SourceStatusRecord, "gse") or SourceStatusRecord(source="gse")
        for k, v in kw.items():
            setattr(row, k, v)
        s.merge(row)


def latest(client):
    r = client.get("/api/v1/generation/latest")
    assert r.status_code == 200
    return r.json()


def test_unavailable_when_enabled_but_empty(migrated_db, gse_enabled, client):
    body = latest(client)
    assert body["freshness"] == "unavailable" and body["value_mw"] is None
    assert body["reason"] == "no_data_yet"


def test_fresh_reading(migrated_db, gse_enabled, client):
    t = utcnow() - timedelta(minutes=2)
    add(t, 73.6)
    body = latest(client)
    assert body["freshness"] == "fresh" and body["value_mw"] == 73.6
    assert body["quality"] == "ACT" and body["quality_flagged"] is False
    assert body["period_seconds"] == 180
    assert datetime.fromisoformat(body["source_observed_at"]) == t
    assert body["reason"] is None


def test_zero_is_a_fresh_value(migrated_db, gse_enabled, client):
    add(utcnow() - timedelta(minutes=1), 0.0)
    body = latest(client)
    assert body["freshness"] == "fresh" and body["value_mw"] == 0.0


def test_non_act_quality_is_flagged(migrated_db, gse_enabled, client):
    add(utcnow() - timedelta(minutes=1), 91.3, "NRE")
    body = latest(client)
    assert body["quality"] == "NRE" and body["quality_flagged"] is True


def test_stale_keeps_last_value_and_original_timestamps(migrated_db, gse_enabled, client):
    t = utcnow() - timedelta(minutes=30)
    add(t, 42.0)
    body = latest(client)
    assert body["freshness"] == "stale" and body["value_mw"] == 42.0
    assert body["reason"] == "source_not_updated"
    assert datetime.fromisoformat(body["retrieved_at"]) == t + timedelta(seconds=80)
    # Subsequent failed polling must not refresh the reading's retrieval time.
    set_status(consecutive_failures=2, last_error="timeout", last_attempt_at=utcnow())
    body2 = latest(client)
    assert body2["reason"] == "source_unreachable"
    assert body2["retrieved_at"] == body["retrieved_at"]


def test_stale_reason_when_disabled(migrated_db, client):
    add(utcnow() - timedelta(hours=2))
    assert latest(client)["reason"] == "ingestion_disabled"


def test_history_points_gaps_and_coverage(migrated_db, client):
    base = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
    for minutes in (0, 3, 6, 15, 18):  # 9 and 12 missing
        add(base + timedelta(minutes=minutes), float(minutes))
    r = client.get(
        "/api/v1/generation/history",
        params={
            "start": (base - timedelta(hours=1)).isoformat(),
            "end": (base + timedelta(minutes=18)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["value_mw"] for p in body["points"]] == [0, 3, 6, 15, 18]
    assert body["cadence_seconds"] == 180
    assert datetime.fromisoformat(body["collection_started_at"]) == base
    # Before collection began is not a gap; the 6 -> 15 hole is.
    assert [
        (datetime.fromisoformat(g["start"]), datetime.fromisoformat(g["end"])) for g in body["gaps"]
    ] == [(base + timedelta(minutes=6), base + timedelta(minutes=15))]


def test_history_trailing_gap_when_source_stops(migrated_db, client):
    t = utcnow() - timedelta(hours=1)
    add(t)
    body = client.get("/api/v1/generation/history").json()
    assert len(body["gaps"]) == 1
    assert datetime.fromisoformat(body["gaps"][0]["start"]) == t


def test_history_no_false_trailing_gap_while_next_file_is_pending(migrated_db, client):
    add(utcnow() - timedelta(minutes=5))  # next period's file may legitimately still be pending
    assert client.get("/api/v1/generation/history").json()["gaps"] == []


def test_history_empty_without_collection(migrated_db, client):
    body = client.get("/api/v1/generation/history").json()
    assert body["points"] == [] and body["gaps"] == [] and body["collection_started_at"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-10-01T00:00:00Z", "end": "2026-11-14T00:00:00Z"},  # > 31 days
        {"start": "2026-11-14T00:00:00Z", "end": "2026-11-13T00:00:00Z"},  # reversed
        {"start": "2026-11-13T00:00:00", "end": "2026-11-14T00:00:00"},  # naive
    ],
)
def test_history_rejects_bad_ranges(migrated_db, client, params):
    assert client.get("/api/v1/generation/history", params=params).status_code == 422


def test_status_reports_gse_states(migrated_db, gse_enabled, client):
    def gse():
        return next(s for s in client.get("/api/v1/status").json()["sources"] if s["id"] == "gse")

    assert gse()["state"] == "degraded"
    set_status(last_success_at=utcnow(), consecutive_failures=0)
    assert gse()["state"] == "ok"
    set_status(consecutive_failures=3, last_error="timeout")
    s = gse()
    assert s["state"] == "down" and s["detail"] == "timeout" and s["consecutive_failures"] == 3
