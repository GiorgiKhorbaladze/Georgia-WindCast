"""Data logic for the Streamlit demo. No Streamlit and no database imports, so it is unit-tested.

The demo reuses the production parsers and rules from ``backend/app`` (strict defusedxml GSE parser,
period/label validation, strict Open-Meteo parser, verified site list) instead of re-implementing
them. It keeps only an in-memory window of recent GSE periods: nothing is stored, and a restart or
sleep of the Streamlit app simply starts the window again. Missing periods stay visible as gaps.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.ingestion import openmeteo  # noqa: E402
from app.ingestion.gse_parser import (  # noqa: E402
    SOURCE_TZ,
    GseParseError,
    WindReading,
    export_file_name,
    parse_wind_export,
)
from app.ingestion.gse_periods import PERIOD, due_labels, validate_label  # noqa: E402
from app.ingestion.http_policy import BackoffPolicy, FetchKind, FetchResult, fetch  # noqa: E402
from app.schemas import SiteSummary  # noqa: E402
from app.sites import SITES  # noqa: E402

log = logging.getLogger("windcast.demo")

GSE_BASE_URL = "https://admin.gse.com.ge/storage/uploads/fact/"
OPENMETEO_BASE_URL = "https://api.open-meteo.com"
PUBLICATION_LAG = timedelta(seconds=75)  # same default as the worker (docs/sources/gse.md)
FRESH_WITHIN = timedelta(seconds=600)  # same default as the API
FORECAST_FRESH_WITHIN = timedelta(hours=12)
QUALITY_ACTUAL = "ACT"

__all__ = [
    "PERIOD",
    "SITES",
    "SOURCE_TZ",
    "ForecastCache",
    "ForecastData",
    "GseRecentWindow",
    "GseSnapshot",
    "SiteSummary",
    "fetch_forecast",
    "forecast_status",
    "gse_client",
    "weather_client",
]


def gse_client(user_agent: str | None = None, timeout: float = 10.0) -> httpx.Client:
    headers = {"Accept": "application/xml, text/xml"}
    if user_agent:
        headers["User-Agent"] = user_agent
    return httpx.Client(timeout=httpx.Timeout(timeout), headers=headers, follow_redirects=False)


def weather_client(user_agent: str | None = None) -> httpx.Client:
    headers = {"Accept": "application/json"}
    if user_agent:
        headers["User-Agent"] = user_agent
    return httpx.Client(timeout=httpx.Timeout(20.0), headers=headers, follow_redirects=False)


# --------------------------------------------------------------------------------------------- GSE


@dataclass(frozen=True, slots=True)
class GsePoint:
    label_utc: datetime
    value_mw: float | None  # None = not published (gap)
    quality: str | None


@dataclass(frozen=True, slots=True)
class GseSnapshot:
    points: list[GsePoint]  # oldest first, one per 3-minute period in the window
    latest: WindReading | None
    status: str  # fresh | unverified | stale | unavailable
    error: str | None  # generic error code for the UI (never raw upstream text)
    checked_at: datetime | None


def freshness(latest: WindReading | None, now: datetime) -> str:
    """Same rules as the API: age from the source label; quality is not freshness."""
    if latest is None:
        return "unavailable"
    if now - latest.period_label_utc > FRESH_WITHIN:
        return "stale"
    if latest.quality != QUALITY_ACTUAL:
        return "unverified"
    return "fresh"


class GseRecentWindow:
    """In-memory window of recent GSE periods, shared by all visitors of one app process.

    Politeness: published files are immutable and fetched once; a refresh runs at most every
    ``min_refresh`` regardless of visitor count; after repeated 404s an older period is abandoned
    as a gap (the newest is always rechecked); failures back off exponentially.
    """

    def __init__(
        self,
        client_factory: Callable[[], httpx.Client],
        *,
        base_url: str = GSE_BASE_URL,
        window_periods: int = 60,
        min_refresh: timedelta = timedelta(seconds=30),
        missing_attempts: int = 3,
        concurrency: int = 4,
        policy: BackoffPolicy | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._base_url = base_url.rstrip("/") + "/"
        self.window_periods = window_periods
        self._min_refresh = min_refresh
        self._missing_attempts = missing_attempts
        self._concurrency = concurrency
        self._policy = policy or BackoffPolicy()
        self._lock = threading.Lock()
        self._readings: dict[datetime, WindReading] = {}
        self._missing: dict[datetime, int] = {}
        self._failures = 0
        self._backoff_until: datetime | None = None
        self._error: str | None = None
        self._last_refresh: datetime | None = None

    def url(self, label: datetime) -> str:
        return self._base_url + export_file_name(label)

    def snapshot(self, now: datetime | None = None) -> GseSnapshot:
        now = now or datetime.now(UTC)
        with self._lock:
            if self._should_refresh(now):
                self._refresh(now)
            return self._build(now)

    def _should_refresh(self, now: datetime) -> bool:
        if self._backoff_until is not None and now < self._backoff_until:
            return False
        return self._last_refresh is None or now - self._last_refresh >= self._min_refresh

    def _refresh(self, now: datetime) -> None:
        self._last_refresh = now
        labels = due_labels(now, PUBLICATION_LAG, self.window_periods)
        oldest = labels[-1]
        self._readings = {k: v for k, v in self._readings.items() if k >= oldest}
        self._missing = {k: v for k, v in self._missing.items() if k >= oldest}
        wanted = [
            label
            for label in labels
            if label not in self._readings
            and (label == labels[0] or self._missing.get(label, 0) < self._missing_attempts)
        ]
        if not wanted:
            return
        with self._client_factory() as client, ThreadPoolExecutor(self._concurrency) as pool:
            results = list(pool.map(lambda lb: (lb, fetch(client, self.url(lb))), wanted))
        failure: str | None = None
        for label, result in results:
            failure = self._apply(label, result, now) or failure
        if failure is None:
            self._failures = 0
            self._backoff_until = None
            self._error = None
        else:
            self._failures += 1
            self._backoff_until = now + self._policy.delay(self._failures)
            self._error = failure

    def _apply(self, label: datetime, result: FetchResult, now: datetime) -> str | None:
        if result.kind is FetchKind.NOT_PUBLISHED:
            self._missing[label] = self._missing.get(label, 0) + 1
            return None
        if result.kind is not FetchKind.OK:
            log.warning("GSE %s: %s %s", label.isoformat(), result.kind.value, result.status)
            return "upstream_unavailable"
        try:
            reading = parse_wind_export(result.body)
            validate_label(reading.period_label_utc, label, now)
        except GseParseError as exc:
            log.warning("GSE %s refused: %s: %s", label.isoformat(), exc.code, exc)
            return exc.code
        self._readings[label] = reading
        self._missing.pop(label, None)
        return None

    def _build(self, now: datetime) -> GseSnapshot:
        labels = due_labels(now, PUBLICATION_LAG, self.window_periods)
        points = []
        for label in reversed(labels):
            r = self._readings.get(label)
            points.append(GsePoint(label, r.value_mw if r else None, r.quality if r else None))
        latest = max(self._readings.values(), key=lambda r: r.period_label_utc, default=None)
        return GseSnapshot(
            points=points,
            latest=latest,
            status=freshness(latest, now),
            error=self._error,
            checked_at=self._last_refresh,
        )


# --------------------------------------------------------------------------------------- forecast


@dataclass(frozen=True, slots=True)
class ForecastRow:
    site_id: str
    valid_at: datetime
    height_m: int
    speed_ms: float | None
    direction_deg: float | None


@dataclass(frozen=True, slots=True)
class ForecastData:
    run_time: datetime
    model_label: str
    rows: list[ForecastRow]
    retrieved_at: datetime


def verified_sites() -> list[SiteSummary]:
    return [s for s in SITES if s.coordinates_verified]


def fetch_forecast(
    client: httpx.Client,
    *,
    base_url: str = OPENMETEO_BASE_URL,
    sites: Sequence[SiteSummary] | None = None,
    forecast_days: int = 4,
    now: datetime | None = None,
) -> ForecastData:
    """One forecast request for all sites, with the model run time read before and after.

    Raises :class:`openmeteo.OpenMeteoError` (or ``httpx.HTTPError``) on any surprise, so the UI
    shows "unavailable" rather than a half-parsed or mixed-run forecast.
    """
    sites = list(sites or verified_sites())
    spec = openmeteo.FORECAST
    assert spec.meta_model is not None
    meta = openmeteo.meta_url(base_url, spec.meta_model)

    def _get(url: str) -> bytes:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content

    run_before = openmeteo.parse_run_time(_get(meta))
    payload = _get(openmeteo.forecast_url(base_url, sites, forecast_days))
    run_after = openmeteo.parse_run_time(_get(meta))
    if run_after != run_before:
        raise openmeteo.OpenMeteoError("model run changed during the fetch; retry later")
    series = openmeteo.parse_response(payload, len(sites), spec.heights)
    rows = [
        ForecastRow(site.id, hv.valid_at, height, hv.speed_ms, hv.direction_deg)
        for site, loc in zip(sites, series, strict=True)
        for height, values in loc.by_height.items()
        for hv in values
    ]
    return ForecastData(
        run_time=run_before,
        model_label=spec.label,
        rows=rows,
        retrieved_at=now or datetime.now(UTC),
    )


def forecast_status(data: ForecastData | None, now: datetime, min_forward_hours: int = 24) -> str:
    """fresh | stale | unavailable, following the API: run age and forward coverage."""
    if data is None:
        return "unavailable"
    forward = [r.valid_at for r in data.rows if r.speed_ms is not None and r.valid_at > now]
    if not forward:
        return "unavailable"
    if now - data.run_time > FORECAST_FRESH_WITHIN:
        return "stale"
    if max(forward) - now < timedelta(hours=min_forward_hours):
        return "stale"
    return "fresh"


def error_code(exc: Exception) -> str:
    """Generic, non-sensitive code for the UI; the details go to the server log only."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return "rate_limited"
    if isinstance(exc, openmeteo.OpenMeteoError):
        return exc.code
    return "upstream_unavailable"


class ForecastCache:
    """Shared forecast for all visitors: refreshed at most every ``refresh``; on failure the last
    good forecast is kept (and shown with its run time and status) and retries back off."""

    def __init__(
        self,
        client_factory: Callable[[], httpx.Client],
        *,
        refresh: timedelta = timedelta(minutes=15),
        policy: BackoffPolicy | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._refresh = refresh
        self._policy = policy or BackoffPolicy(
            base=timedelta(minutes=5), maximum=timedelta(hours=2)
        )
        self._lock = threading.Lock()
        self.data: ForecastData | None = None
        self.error: str | None = None
        self._last_attempt: datetime | None = None
        self._failures = 0
        self._backoff_until: datetime | None = None

    def get(self, now: datetime | None = None) -> tuple[ForecastData | None, str | None]:
        now = now or datetime.now(UTC)
        with self._lock:
            due = self._last_attempt is None or now - self._last_attempt >= self._refresh
            if due and (self._backoff_until is None or now >= self._backoff_until):
                self._last_attempt = now
                try:
                    with self._client_factory() as client:
                        self.data = fetch_forecast(client, now=now)
                    self.error, self._failures, self._backoff_until = None, 0, None
                except Exception as exc:  # any surprise keeps the last good forecast
                    log.warning("forecast failed: %r", exc)
                    self.error = error_code(exc)
                    self._failures += 1
                    self._backoff_until = now + self._policy.delay(self._failures)
            return self.data, self.error
