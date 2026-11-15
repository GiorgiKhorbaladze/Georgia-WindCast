"""GSE national wind ingestion job.

Each tick asks only for period files that are due (label + publication lag has passed) and not yet
stored, newest first, with a small per-tick request budget. A 404 means "not published (yet)"
and is not a failure. Transport errors, 429/5xx, unexpected content and schema drift are failures:
they advance an exponential backoff (honouring Retry-After) persisted in ``source_status``.

Writes are idempotent on (source, metric, period_label_at). Nothing here ever creates a reading
that GSE did not publish, and an unsuccessful poll never touches existing readings, so a stale
value can never look refreshed.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.ingestion.gse_parser import (
    PARSER_VERSION,
    GseFutureLabelError,
    GseLabelError,
    GseParseError,
    export_file_name,
    parse_wind_export,
)
from app.ingestion.http_policy import BackoffPolicy, FetchKind, FetchResult, fetch
from app.models import GenerationReading, SourceStatusRecord
from app.timeutil import utcnow

log = logging.getLogger("windcast.ingestion.gse")

SOURCE_ID = "gse"
METRIC_WIND = "wind_total"
PERIOD = timedelta(minutes=3)


def floor_period(t: datetime) -> datetime:
    """Floor an aware datetime to the 3-minute grid (GSE labels fall on :00, :03, ...)."""
    t = t.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % 3)


def due_labels(now: datetime, lag: timedelta, count: int) -> list[datetime]:
    """Period labels that should be published by ``now``, newest first."""
    newest = floor_period(now - lag)
    return [newest - i * PERIOD for i in range(count)]


@dataclass
class TickReport:
    requested: int = 0
    stored: int = 0
    duplicates: int = 0
    not_published: int = 0
    failure: str | None = None
    skipped_backoff: bool = False
    stored_labels: list[datetime] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StoreOutcome:
    inserted: bool
    revised: bool


# Clock skew allowance between this host and GSE before a label counts as "in the future".
FUTURE_LABEL_TOLERANCE = timedelta(seconds=60)


def validate_label(reading_label: datetime, expected_label: datetime | None, now: datetime) -> None:
    """Refuse a payload whose embedded period does not match the requested file, or lies ahead."""
    if expected_label is not None and reading_label != expected_label:
        raise GseLabelError(
            f"embedded period {reading_label.isoformat()} does not match requested "
            f"{expected_label.isoformat()}"
        )
    if reading_label > now + FUTURE_LABEL_TOLERANCE:
        raise GseFutureLabelError(f"embedded period {reading_label.isoformat()} is in the future")


def store_reading(
    session: Session,
    result: FetchResult,
    retrieved_at: datetime,
    expected_label: datetime | None = None,
) -> StoreOutcome:
    reading = parse_wind_export(result.body)
    # Validated before anything is written, so a mislabelled file can never become data.
    validate_label(reading.period_label_utc, expected_label, retrieved_at)
    digest = hashlib.sha256(result.body).hexdigest()
    values = {
        "source": SOURCE_ID,
        "metric": METRIC_WIND,
        "period_label_at": reading.period_label_utc,
        "period_label_local": reading.period_label_local,
        "value_mw": reading.value_mw,
        "quality": reading.quality,
        "source_url": result.url,
        "etag": result.etag,
        "source_last_modified": result.last_modified,
        "payload_sha256": digest,
        "parser_version": PARSER_VERSION,
        "retrieved_at": retrieved_at,
    }
    inserted = session.execute(
        insert(GenerationReading)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_generation_period")
        .returning(GenerationReading.id)
    ).scalar()
    if inserted is not None:
        return StoreOutcome(inserted=True, revised=False)

    existing = session.execute(
        select(GenerationReading).where(
            GenerationReading.source == SOURCE_ID,
            GenerationReading.metric == METRIC_WIND,
            GenerationReading.period_label_at == reading.period_label_utc,
        )
    ).scalar_one()
    if existing.payload_sha256 == digest:
        return StoreOutcome(inserted=False, revised=False)
    # The source republished different content for a period it had already published.
    log.warning(
        "GSE revised period %s: %s MW (%s) -> %s MW (%s)",
        reading.period_label_local,
        existing.value_mw,
        existing.quality,
        reading.value_mw,
        reading.quality,
    )
    for key in (
        "value_mw",
        "quality",
        "etag",
        "source_last_modified",
        "payload_sha256",
        "parser_version",
        "retrieved_at",
    ):
        setattr(existing, key, values[key])
    existing.revision += 1
    return StoreOutcome(inserted=False, revised=True)


def _status(session: Session) -> SourceStatusRecord:
    status = session.get(SourceStatusRecord, SOURCE_ID, with_for_update=True)
    if status is None:
        status = SourceStatusRecord(source=SOURCE_ID, consecutive_failures=0)
        session.add(status)
        session.flush()
    return status


class GseIngestionJob:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client,
        policy: BackoffPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.policy = policy or BackoffPolicy()
        # Labels that returned 404, with attempt counts. In memory only: a restart simply
        # retries a few recent periods, which is harmless.
        self._missing: dict[datetime, int] = {}

    def _url(self, label: datetime) -> str:
        return self.settings.gse_base_url.rstrip("/") + "/" + export_file_name(label)

    def _candidates(self, session: Session, now: datetime) -> list[datetime]:
        s = self.settings
        labels = due_labels(
            now, timedelta(seconds=s.gse_publication_lag_seconds), s.gse_catchup_periods
        )
        stored = set(
            session.execute(
                select(GenerationReading.period_label_at).where(
                    GenerationReading.source == SOURCE_ID,
                    GenerationReading.metric == METRIC_WIND,
                    GenerationReading.period_label_at >= labels[-1],
                )
            ).scalars()
        )
        newest = labels[0]
        self._missing = {k: v for k, v in self._missing.items() if k >= labels[-1]}
        out = []
        for label in labels:
            if label in stored:
                continue
            if label != newest and self._missing.get(label, 0) >= s.gse_missing_attempts:
                continue  # give up on a period GSE apparently never published; leave the gap
            out.append(label)
        return out[: s.gse_max_requests_per_tick]

    def tick(self, session: Session, now: datetime | None = None) -> TickReport:
        """Run one polling step inside the caller's transaction."""
        now = now or utcnow()
        report = TickReport()
        status = _status(session)
        if status.backoff_until is not None and status.backoff_until > now:
            report.skipped_backoff = True
            return report

        for label in self._candidates(session, now):
            result = fetch(self.client, self._url(label))
            report.requested += 1
            status.last_attempt_at = now
            status.last_http_status = result.status

            if result.kind is FetchKind.NOT_PUBLISHED:
                self._missing[label] = self._missing.get(label, 0) + 1
                report.not_published += 1
                continue
            if result.kind is FetchKind.OK:
                try:
                    with session.begin_nested():
                        outcome = store_reading(
                            session, result, retrieved_at=utcnow(), expected_label=label
                        )
                except GseParseError as exc:
                    self._fail(status, now, f"{exc.code}: {exc}", None, report)
                    break
                if outcome.inserted or outcome.revised:
                    report.stored += 1
                    report.stored_labels.append(label)
                else:
                    report.duplicates += 1
                self._missing.pop(label, None)
                status.last_success_at = now
                status.consecutive_failures = 0
                status.backoff_until = None
                status.last_error = None
                continue
            detail = f"{result.kind.value}" + (f" ({result.detail})" if result.detail else "")
            if result.status:
                detail += f" HTTP {result.status}"
            self._fail(status, now, detail, result.retry_after, report)
            break
        return report

    def _fail(
        self,
        status: SourceStatusRecord,
        now: datetime,
        detail: str,
        retry_after: timedelta | None,
        report: TickReport,
    ) -> None:
        status.consecutive_failures += 1
        status.last_failure_at = now
        status.last_error = detail[:500]
        status.backoff_until = now + self.policy.delay(status.consecutive_failures, retry_after)
        report.failure = detail
        log.warning(
            "GSE fetch failed (%s), failure #%d, backing off until %s",
            detail,
            status.consecutive_failures,
            status.backoff_until.isoformat(),
        )


def build_client(settings: Settings) -> httpx.Client:
    headers = {"Accept": "application/xml, text/xml"}
    if settings.gse_user_agent:
        headers["User-Agent"] = settings.gse_user_agent
    return httpx.Client(
        timeout=httpx.Timeout(settings.gse_timeout_seconds),
        headers=headers,
        follow_redirects=False,
    )
