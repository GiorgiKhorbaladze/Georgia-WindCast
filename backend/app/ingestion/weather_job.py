"""Open-Meteo weather ingestion for the three verified sites.

Forecast (DWD ICON global): the model's ``meta.json`` is checked; only when a new run has been
published is the forecast fetched, for all sites in one request. The run time is checked again
afterwards; if the run changed during the fetch the data is discarded and retried on the next tick,
so values are never attributed to the wrong run. Only valid times at or after the run's
initialisation are stored under that run, because Open-Meteo fills earlier hours from older runs.

Reanalysis (ERA5): fetched at most once per ``weather_reanalysis_interval`` for a trailing window
and upserted, because ERA5 preliminary values are revised.

Failures use the same persisted backoff policy as GSE, per source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.ingestion.http_policy import BackoffPolicy, FetchKind, FetchResult, fetch
from app.ingestion.openmeteo import (
    FORECAST,
    REANALYSIS,
    LocationSeries,
    OpenMeteoError,
    ProductSpec,
    archive_url,
    forecast_url,
    meta_url,
    parse_response,
    parse_run_time,
)
from app.models import SourceStatusRecord, WeatherValue
from app.schemas import SiteSummary
from app.sites import SITES
from app.timeutil import utcnow

log = logging.getLogger("windcast.ingestion.weather")

SOURCE_FORECAST = "open-meteo-forecast"
SOURCE_REANALYSIS = "open-meteo-reanalysis"
PROVIDER = "open-meteo"
REANALYSIS_RUN_REF = "era5"


@dataclass
class WeatherTickReport:
    source: str
    requested: int = 0
    stored: int = 0
    skipped: str | None = None
    failure: str | None = None
    run_at: datetime | None = None


def _status(session: Session, source: str) -> SourceStatusRecord:
    row = session.get(SourceStatusRecord, source, with_for_update=True)
    if row is None:
        row = SourceStatusRecord(source=source, consecutive_failures=0)
        session.add(row)
        session.flush()
    return row


def _rows(
    spec: ProductSpec,
    sites: tuple[SiteSummary, ...],
    series: list[LocationSeries],
    run_ref: str,
    run_at: datetime | None,
    retrieved_at: datetime,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for site, loc in zip(sites, series, strict=True):
        for height, values in loc.by_height.items():
            for v in values:
                if run_at is not None and v.valid_at < run_at:
                    continue  # not produced by this run (Open-Meteo back-fills from older runs)
                rows.append(
                    {
                        "site_id": site.id,
                        "product": spec.product,
                        "provider": PROVIDER,
                        "model": spec.model,
                        "run_ref": run_ref,
                        "run_at": run_at,
                        "valid_at": v.valid_at,
                        "height_m": height,
                        "speed_ms": v.speed_ms,
                        "direction_deg": v.direction_deg,
                        "grid_latitude": loc.grid_latitude,
                        "grid_longitude": loc.grid_longitude,
                        "grid_elevation_m": loc.grid_elevation_m,
                        "retrieved_at": retrieved_at,
                    }
                )
    return rows


def store_rows(session: Session, rows: list[dict[str, object]], *, update: bool) -> int:
    if not rows:
        return 0
    stored = 0
    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = insert(WeatherValue).values(chunk)
        if update:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_weather_value",
                set_={
                    "speed_ms": stmt.excluded.speed_ms,
                    "direction_deg": stmt.excluded.direction_deg,
                    "retrieved_at": stmt.excluded.retrieved_at,
                    "grid_latitude": stmt.excluded.grid_latitude,
                    "grid_longitude": stmt.excluded.grid_longitude,
                    "grid_elevation_m": stmt.excluded.grid_elevation_m,
                },
            )
        else:
            stmt = stmt.on_conflict_do_nothing(constraint="uq_weather_value")
        stored += len(session.execute(stmt.returning(WeatherValue.id)).all())
    return stored


class WeatherIngestionJob:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client,
        policy: BackoffPolicy | None = None,
        sites: tuple[SiteSummary, ...] = SITES,
    ) -> None:
        self.settings = settings
        self.client = client
        self.policy = policy or BackoffPolicy(base=timedelta(minutes=5))
        self.sites = tuple(s for s in sites if s.coordinates_verified)

    # -- failure bookkeeping ------------------------------------------------------------------
    def _fail(
        self,
        status: SourceStatusRecord,
        now: datetime,
        detail: str,
        retry_after: timedelta | None,
        report: WeatherTickReport,
    ) -> None:
        status.consecutive_failures += 1
        status.last_failure_at = now
        status.last_error = detail[:500]
        status.backoff_until = now + self.policy.delay(status.consecutive_failures, retry_after)
        report.failure = detail
        log.warning(
            "%s failed (%s), failure #%d, backing off until %s",
            report.source,
            detail,
            status.consecutive_failures,
            status.backoff_until.isoformat(),
        )

    def _ok(self, status: SourceStatusRecord, now: datetime) -> None:
        status.last_success_at = now
        status.consecutive_failures = 0
        status.backoff_until = None
        status.last_error = None

    def _fetch(
        self, status: SourceStatusRecord, url: str, now: datetime, report: WeatherTickReport
    ) -> FetchResult | None:
        result = fetch(self.client, url, expect="json")
        report.requested += 1
        status.last_attempt_at = now
        status.last_http_status = result.status
        if result.kind is FetchKind.OK:
            return result
        detail = result.kind.value + (f" HTTP {result.status}" if result.status else "")
        if result.detail:
            detail += f" ({result.detail})"
        self._fail(status, now, detail, result.retry_after, report)
        return None

    # -- forecast -----------------------------------------------------------------------------
    def _run_time(
        self, status: SourceStatusRecord, now: datetime, report: WeatherTickReport
    ) -> datetime | None:
        assert FORECAST.meta_model
        res = self._fetch(
            status, meta_url(self.settings.openmeteo_base_url, FORECAST.meta_model), now, report
        )
        if res is None:
            return None
        try:
            return parse_run_time(res.body)
        except OpenMeteoError as exc:
            self._fail(status, now, f"{exc.code}: {exc}", None, report)
            return None

    def latest_stored_run(self, session: Session) -> datetime | None:
        return session.execute(
            select(func.max(WeatherValue.run_at)).where(
                WeatherValue.product == FORECAST.product, WeatherValue.model == FORECAST.model
            )
        ).scalar()

    def tick_forecast(self, session: Session, now: datetime | None = None) -> WeatherTickReport:
        now = now or utcnow()
        report = WeatherTickReport(SOURCE_FORECAST)
        status = _status(session, SOURCE_FORECAST)
        if status.backoff_until is not None and status.backoff_until > now:
            report.skipped = "backoff"
            return report

        run_at = self._run_time(status, now, report)
        if run_at is None:
            return report
        report.run_at = run_at
        if self.latest_stored_run(session) == run_at:
            self._ok(status, now)
            report.skipped = "run_already_stored"
            return report

        url = forecast_url(
            self.settings.openmeteo_base_url, self.sites, self.settings.weather_forecast_days
        )
        res = self._fetch(status, url, now, report)
        if res is None:
            return report
        try:
            series = parse_response(res.body, len(self.sites), FORECAST.heights)
        except OpenMeteoError as exc:
            self._fail(status, now, f"{exc.code}: {exc}", None, report)
            return report

        run_after = self._run_time(status, now, report)
        if run_after is None:
            return report
        if run_after != run_at:
            report.skipped = "run_changed_during_fetch"
            log.info(
                "forecast run changed during fetch (%s -> %s); retrying later", run_at, run_after
            )
            return report

        rows = _rows(FORECAST, self.sites, series, run_at.isoformat(), run_at, utcnow())
        report.stored = store_rows(session, rows, update=False)
        self._ok(status, now)
        return report

    # -- reanalysis ---------------------------------------------------------------------------
    def tick_reanalysis(self, session: Session, now: datetime | None = None) -> WeatherTickReport:
        now = now or utcnow()
        report = WeatherTickReport(SOURCE_REANALYSIS)
        status = _status(session, SOURCE_REANALYSIS)
        if status.backoff_until is not None and status.backoff_until > now:
            report.skipped = "backoff"
            return report
        interval = timedelta(seconds=self.settings.weather_reanalysis_interval_seconds)
        if status.last_success_at is not None and now - status.last_success_at < interval:
            report.skipped = "not_due"
            return report

        end = (now - timedelta(days=1)).date()
        start = end - timedelta(days=self.settings.weather_reanalysis_days - 1)
        url = archive_url(
            self.settings.openmeteo_archive_base_url, self.sites, start.isoformat(), end.isoformat()
        )
        res = self._fetch(status, url, now, report)
        if res is None:
            return report
        try:
            series = parse_response(res.body, len(self.sites), REANALYSIS.heights)
        except OpenMeteoError as exc:
            self._fail(status, now, f"{exc.code}: {exc}", None, report)
            return report
        # Trailing hours not yet in ERA5 come back as null; they are not stored.
        rows = [
            r
            for r in _rows(REANALYSIS, self.sites, series, REANALYSIS_RUN_REF, None, utcnow())
            if r["speed_ms"] is not None or r["direction_deg"] is not None
        ]
        report.stored = store_rows(session, rows, update=True)
        self._ok(status, now)
        return report

    # -- retention ----------------------------------------------------------------------------
    def prune(self, session: Session, now: datetime | None = None) -> int:
        """Drop long-lead values of old forecast runs; short leads are kept as history."""
        now = now or utcnow()
        cutoff = now - timedelta(days=self.settings.weather_forecast_retention_days)
        result = session.execute(
            delete(WeatherValue).where(
                WeatherValue.product == FORECAST.product,
                WeatherValue.run_at < cutoff,
                WeatherValue.valid_at - WeatherValue.run_at > timedelta(hours=12),
            )
        )
        return result.rowcount or 0  # type: ignore[attr-defined]


def build_weather_client(settings: Settings) -> httpx.Client:
    headers = {"Accept": "application/json"}
    if settings.weather_user_agent:
        headers["User-Agent"] = settings.weather_user_agent
    return httpx.Client(timeout=httpx.Timeout(20.0), headers=headers, follow_redirects=False)
