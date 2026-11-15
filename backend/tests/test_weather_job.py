import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.ingestion.http_policy import BackoffPolicy
from app.ingestion.weather_job import WeatherIngestionJob
from app.models import SourceStatusRecord, WeatherValue
from tests.weather_fixtures import (
    META_RUN_T,
    REAL_ARCHIVE_BYTES,
    REAL_FORECAST_BYTES,
    REAL_META_BYTES,
    REAL_RUN_T,
    forecast_like,
    meta,
)

pytestmark = pytest.mark.db
RUN = datetime.fromtimestamp(META_RUN_T, UTC)
NOW = RUN + timedelta(hours=3)
JSON = {"content-type": "application/json; charset=utf-8"}


class FakeOpenMeteo:
    def __init__(self):
        self.metas = [meta()]
        self.forecast = json.dumps(forecast_like()).encode()
        self.archive = REAL_ARCHIVE_BYTES
        self.override = None
        self.paths: list[str] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request):
        self.paths.append(request.url.path)
        if self.override:
            return self.override(request)
        if request.url.path.endswith("meta.json"):
            body = self.metas[0] if len(self.metas) == 1 else self.metas.pop(0)
            return httpx.Response(200, content=body, headers=JSON)
        if request.url.path == "/v1/forecast":
            return httpx.Response(200, content=self.forecast, headers=JSON)
        if request.url.path == "/v1/archive":
            return httpx.Response(200, content=self.archive, headers=JSON)
        return httpx.Response(404)


def job(fake):
    return WeatherIngestionJob(
        get_settings(), fake.client, BackoffPolicy(base=timedelta(minutes=5), jitter=0.0)
    )


def run(step, now=NOW):
    with get_sessionmaker()() as s, s.begin():
        return step(s, now=now)


def count(**filters):
    with get_sessionmaker()() as s:
        q = select(func.count()).select_from(WeatherValue)
        for k, v in filters.items():
            q = q.where(getattr(WeatherValue, k) == v)
        return s.execute(q).scalar_one()


def test_forecast_stores_only_values_from_the_run_onwards(migrated_db):
    fake = FakeOpenMeteo()
    report = run(job(fake).tick_forecast)
    assert report.failure is None and report.run_at == RUN
    # fixture: 48 hourly values from 00Z; run at 06Z -> 42 valid times x 4 heights x 3 sites
    assert report.stored == 42 * 4 * 3 == count(product="forecast")
    with get_sessionmaker()() as s:
        earliest = s.execute(select(func.min(WeatherValue.valid_at))).scalar()
        heights = set(s.execute(select(WeatherValue.height_m).distinct()).scalars())
    assert earliest == RUN
    assert heights == {10, 80, 120, 180}
    # one forecast request for all three sites, bracketed by two run-time checks
    assert fake.paths == [
        "/data/dwd_icon/static/meta.json",
        "/v1/forecast",
        "/data/dwd_icon/static/meta.json",
    ]


def test_real_forecast_recording_is_stored_completely(migrated_db):
    fake = FakeOpenMeteo()
    fake.metas = [REAL_META_BYTES]
    fake.forecast = REAL_FORECAST_BYTES
    real_run = datetime.fromtimestamp(REAL_RUN_T, UTC)
    report = run(job(fake).tick_forecast, real_run + timedelta(hours=6))
    assert report.failure is None and report.run_at == real_run
    assert report.stored == 96 * 4 * 3 == count(product="forecast", run_at=real_run)
    with get_sessionmaker()() as s:
        row = s.execute(
            select(WeatherValue)
            .where(WeatherValue.site_id == "zemo-wind", WeatherValue.height_m == 120)
            .order_by(WeatherValue.valid_at)
            .limit(1)
        ).scalar_one()
    assert (row.speed_ms, row.direction_deg) == (4.22, 265)
    assert (row.grid_latitude, row.grid_longitude) == (41.875, 44.375)


def test_same_run_is_not_refetched(migrated_db):
    fake = FakeOpenMeteo()
    j = job(fake)
    run(j.tick_forecast)
    fake.paths.clear()
    report = run(j.tick_forecast)
    assert report.skipped == "run_already_stored"
    assert fake.paths == ["/data/dwd_icon/static/meta.json"]


def test_run_change_during_fetch_discards_data(migrated_db):
    fake = FakeOpenMeteo()
    fake.metas = [meta(META_RUN_T), meta(META_RUN_T + 3 * 3600)]
    report = run(job(fake).tick_forecast)
    assert report.skipped == "run_changed_during_fetch"
    assert count() == 0


def test_rate_limit_honours_retry_after_and_writes_nothing(migrated_db):
    fake = FakeOpenMeteo()
    fake.override = lambda _r: httpx.Response(429, headers={"retry-after": "12129"})
    report = run(job(fake).tick_forecast)
    assert "rate_limited" in report.failure
    with get_sessionmaker()() as s:
        st = s.get(SourceStatusRecord, "open-meteo-forecast")
    assert st.backoff_until == NOW + timedelta(hours=1)  # Retry-After capped at 1 h
    assert count() == 0
    fake.paths.clear()
    assert run(job(fake).tick_forecast, NOW + timedelta(minutes=30)).skipped == "backoff"
    assert fake.paths == []


def test_provider_error_body_is_a_failure(migrated_db):
    fake = FakeOpenMeteo()
    fake.forecast = b'{"error":true,"reason":"Cannot initialize WeatherVariable"}'
    report = run(job(fake).tick_forecast)
    assert report.failure.startswith("schema_drift")
    assert count() == 0


def test_reanalysis_upserts_and_is_rate_limited_by_interval(migrated_db):
    fake = FakeOpenMeteo()
    j = job(fake)
    first = run(j.tick_reanalysis)
    assert first.stored == 48 * 2 * 3 == count(product="reanalysis")
    again = run(j.tick_reanalysis, NOW + timedelta(hours=1))
    assert again.skipped == "not_due"
    # a later revision of the same hours updates in place, no duplicates
    revised = json.loads(REAL_ARCHIVE_BYTES)
    revised[0]["hourly"]["wind_speed_100m"][0] = 9.5
    fake.archive = json.dumps(revised).encode()
    run(j.tick_reanalysis, NOW + timedelta(days=2))
    assert count(product="reanalysis") == 48 * 2 * 3
    with get_sessionmaker()() as s:
        v = s.execute(
            select(WeatherValue.speed_ms)
            .where(
                WeatherValue.product == "reanalysis",
                WeatherValue.site_id == "ruisi",
                WeatherValue.height_m == 100,
            )
            .order_by(WeatherValue.valid_at)
            .limit(1)
        ).scalar()
    assert v == 9.5


def test_prune_keeps_short_leads_of_old_runs(migrated_db):
    fake = FakeOpenMeteo()
    j = job(fake)
    run(j.tick_forecast)
    with get_sessionmaker()() as s, s.begin():
        pruned = j.prune(s, now=RUN + timedelta(days=40))
    assert pruned > 0
    with get_sessionmaker()() as s:
        leads = s.execute(select(func.max(WeatherValue.valid_at - WeatherValue.run_at))).scalar()
    assert leads <= timedelta(hours=12)
