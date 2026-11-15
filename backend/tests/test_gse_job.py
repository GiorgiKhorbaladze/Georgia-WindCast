from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.ingestion.gse_job import GseIngestionJob, store_reading
from app.ingestion.http_policy import BackoffPolicy, FetchKind, FetchResult
from app.models import GenerationReading, SourceStatusRecord
from tests.gse_fixtures import REAL_ACT, REAL_ACT_NAME, REAL_NRE, REAL_NRE_NAME, mutate

pytestmark = pytest.mark.db

# 20:11:00 UTC: with the 75 s publication lag the newest due label is 20:09 (00:09 Tbilisi).
NOW = datetime(2026, 11, 14, 20, 11, 0, tzinfo=UTC)
XML = {"content-type": "text/xml", "etag": '"e1"'}


class FakeGse:
    """MockTransport-backed GSE: serves given files, 404 otherwise, records requests."""

    def __init__(self, files=None, override=None):
        self.files = dict(files or {})
        self.override = override
        self.requests: list[str] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        self.requests.append(name)
        if self.override is not None:
            return self.override(request)
        if name in self.files:
            return httpx.Response(200, content=self.files[name], headers=XML)
        return httpx.Response(404)


def make_job(fake: FakeGse) -> GseIngestionJob:
    return GseIngestionJob(
        get_settings(), fake.client, BackoffPolicy(base=timedelta(seconds=60), jitter=0.0)
    )


def tick(job, now=NOW):
    with get_sessionmaker()() as s, s.begin():
        return job.tick(s, now=now)


def count_readings() -> int:
    with get_sessionmaker()() as s:
        return s.execute(select(func.count()).select_from(GenerationReading)).scalar_one()


def status() -> SourceStatusRecord:
    with get_sessionmaker()() as s:
        return s.get(SourceStatusRecord, "gse")


def test_tick_stores_newest_due_period_with_provenance(migrated_db):
    fake = FakeGse({REAL_ACT_NAME: REAL_ACT})
    report = tick(make_job(fake))
    assert report.stored == 1 and report.failure is None
    assert fake.requests[0] == REAL_ACT_NAME  # newest first
    assert report.requested == get_settings().gse_max_requests_per_tick  # budget respected
    with get_sessionmaker()() as s:
        row = s.execute(select(GenerationReading)).scalar_one()
    assert row.value_mw == pytest.approx(73.599297)
    assert row.period_label_at == datetime(2026, 11, 14, 20, 9, tzinfo=UTC)
    assert row.period_label_local == "15.11.2026 00:09:00"
    assert row.quality == "ACT"
    assert row.source_url.endswith(REAL_ACT_NAME)
    assert row.etag == '"e1"' and len(row.payload_sha256) == 64
    assert row.retrieved_at > row.period_label_at
    st = status()
    assert st.consecutive_failures == 0 and st.last_success_at == NOW


def test_stored_period_is_not_requested_again(migrated_db):
    fake = FakeGse({REAL_ACT_NAME: REAL_ACT})
    job = make_job(fake)
    tick(job)
    fake.requests.clear()
    tick(job)
    assert REAL_ACT_NAME not in fake.requests
    assert count_readings() == 1


def test_store_is_idempotent_and_detects_revisions(migrated_db):
    ok = FetchResult(FetchKind.OK, "u", status=200, body=REAL_ACT)
    with get_sessionmaker()() as s, s.begin():
        assert store_reading(s, ok, NOW).inserted
    with get_sessionmaker()() as s, s.begin():
        out = store_reading(s, ok, NOW)
        assert not out.inserted and not out.revised
    revised = FetchResult(
        FetchKind.OK, "u", status=200, body=mutate(b"VALUE='73.599297'", b"VALUE='70.000000'")
    )
    with get_sessionmaker()() as s, s.begin():
        assert store_reading(s, revised, NOW).revised
    with get_sessionmaker()() as s:
        row = s.execute(select(GenerationReading)).scalar_one()
    assert row.value_mw == 70.0 and row.revision == 1
    assert count_readings() == 1


def test_rate_limit_backs_off_and_honours_retry_after(migrated_db):
    fake = FakeGse(override=lambda _r: httpx.Response(429, headers={"retry-after": "600"}))
    job = make_job(fake)
    report = tick(job)
    assert report.failure and "rate_limited" in report.failure
    assert fake.requests == [REAL_ACT_NAME]  # stops at the first failure
    st = status()
    assert st.consecutive_failures == 1 and st.last_http_status == 429
    assert st.backoff_until == NOW + timedelta(seconds=600)
    # During backoff no request is made at all.
    fake.requests.clear()
    assert tick(job, NOW + timedelta(seconds=300)).skipped_backoff
    assert fake.requests == []
    assert count_readings() == 0


@pytest.mark.parametrize(
    "override",
    [
        lambda _r: httpx.Response(500),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("t", request=r)),
        lambda _r: httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"}),
    ],
)
def test_failures_grow_backoff_and_never_write(migrated_db, override):
    fake = FakeGse(override=override)
    job = make_job(fake)
    tick(job)
    first = status()
    tick(job, first.backoff_until + timedelta(seconds=1))
    second = status()
    assert second.consecutive_failures == 2
    assert (second.backoff_until - second.last_failure_at) > (first.backoff_until - NOW)
    assert count_readings() == 0


def test_schema_drift_is_a_failure_and_stores_nothing(migrated_db):
    drift = mutate(b"TOTAL WIND PLANTS", b"TOTAL WIND FARMS")
    fake = FakeGse({REAL_ACT_NAME: drift})
    report = tick(make_job(fake))
    assert report.failure.startswith("schema_drift")
    assert count_readings() == 0
    assert status().consecutive_failures == 1


def test_recovery_resets_failure_state(migrated_db):
    fake = FakeGse(override=lambda _r: httpx.Response(502))
    job = make_job(fake)
    tick(job)
    fake.override = None
    fake.files = {REAL_ACT_NAME: REAL_ACT}
    report = tick(job, status().backoff_until + timedelta(seconds=1))
    assert report.stored == 1
    st = status()
    assert st.consecutive_failures == 0 and st.backoff_until is None and st.last_error is None


def test_catch_up_fills_real_missed_periods_only(migrated_db):
    fake = FakeGse({REAL_ACT_NAME: REAL_ACT, REAL_NRE_NAME: REAL_NRE})
    report = tick(make_job(fake))
    assert report.stored == 2 and report.not_published == 2
    with get_sessionmaker()() as s:
        labels = (
            s.execute(
                select(GenerationReading.period_label_at).order_by(
                    GenerationReading.period_label_at
                )
            )
            .scalars()
            .all()
        )
    assert labels == [
        datetime(2026, 11, 14, 20, 3, tzinfo=UTC),
        datetime(2026, 11, 14, 20, 9, tzinfo=UTC),
    ]  # 20:06 stays a gap


def test_unpublished_older_periods_are_abandoned_after_attempts(migrated_db, monkeypatch):
    monkeypatch.setenv("WINDCAST_GSE_CATCHUP_PERIODS", "2")
    monkeypatch.setenv("WINDCAST_GSE_MISSING_ATTEMPTS", "2")
    get_settings.cache_clear()
    fake = FakeGse()
    job = make_job(fake)
    for _ in range(4):
        tick(job)
    older = "GSE_EXPORT_NEW_PERIOD_03M_15112026_0006.XML"
    assert fake.requests.count(older) == 2  # given up after 2 attempts
    assert fake.requests.count(REAL_ACT_NAME) == 4  # newest keeps being checked
    assert status().consecutive_failures == 0  # 404s are not failures


def test_mismatched_embedded_label_is_rejected_before_persistence(migrated_db):
    """A file whose embedded Export Time differs from the requested period is not data."""
    other = "GSE_EXPORT_NEW_PERIOD_03M_15112026_0006.XML"  # requested 20:06, embedded 20:09
    fake = FakeGse({REAL_ACT_NAME: REAL_ACT, other: REAL_ACT})
    report = tick(make_job(fake))
    assert report.stored == 1  # only the correctly labelled file
    assert report.failure is not None and report.failure.startswith("label_mismatch")
    with get_sessionmaker()() as s:
        labels = s.execute(select(GenerationReading.period_label_at)).scalars().all()
    assert labels == [datetime(2026, 11, 14, 20, 9, tzinfo=UTC)]
    assert status().consecutive_failures == 1


def test_future_embedded_label_is_rejected(migrated_db):
    ok = FetchResult(FetchKind.OK, "u", status=200, body=REAL_ACT)
    label = datetime(2026, 11, 14, 20, 9, tzinfo=UTC)
    from app.ingestion.gse_parser import GseFutureLabelError

    with pytest.raises(GseFutureLabelError), get_sessionmaker()() as s, s.begin():
        store_reading(s, ok, retrieved_at=label - timedelta(hours=1), expected_label=label)
    assert count_readings() == 0
    # within the clock tolerance it is accepted
    with get_sessionmaker()() as s, s.begin():
        assert store_reading(s, ok, retrieved_at=label - timedelta(seconds=30)).inserted
