"""Fetch outcome classification and backoff policy for polite polling."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum

import httpx

from app.timeutil import utcnow


class FetchKind(StrEnum):
    OK = "ok"
    NOT_PUBLISHED = "not_published"  # 404: the period file does not exist (yet). Not a failure.
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    UNEXPECTED_CONTENT = "unexpected_content"


FAILURES = {
    FetchKind.RATE_LIMITED,
    FetchKind.SERVER_ERROR,
    FetchKind.CLIENT_ERROR,
    FetchKind.TIMEOUT,
    FetchKind.NETWORK_ERROR,
    FetchKind.UNEXPECTED_CONTENT,
}


@dataclass(frozen=True, slots=True)
class FetchResult:
    kind: FetchKind
    url: str
    status: int | None = None
    body: bytes = b""
    etag: str | None = None
    last_modified: datetime | None = None
    retry_after: timedelta | None = None
    detail: str | None = None

    @property
    def is_failure(self) -> bool:
        return self.kind in FAILURES


def parse_retry_after(value: str | None, now: datetime | None = None) -> timedelta | None:
    """Parse Retry-After as delta-seconds or HTTP-date. Returns None if absent or invalid."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return timedelta(seconds=int(value))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    delta = when - (now or utcnow())
    return max(delta, timedelta(0))


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def fetch(client: httpx.Client, url: str) -> FetchResult:
    try:
        resp = client.get(url)
    except httpx.TimeoutException as exc:
        return FetchResult(FetchKind.TIMEOUT, url, detail=type(exc).__name__)
    except httpx.TransportError as exc:
        return FetchResult(FetchKind.NETWORK_ERROR, url, detail=type(exc).__name__)

    status = resp.status_code
    if status == 404:
        return FetchResult(FetchKind.NOT_PUBLISHED, url, status=status)
    if status == 429 or status == 503:
        kind = FetchKind.RATE_LIMITED if status == 429 else FetchKind.SERVER_ERROR
        return FetchResult(
            kind, url, status=status, retry_after=parse_retry_after(resp.headers.get("retry-after"))
        )
    if status >= 500:
        return FetchResult(FetchKind.SERVER_ERROR, url, status=status)
    if status != 200:
        return FetchResult(FetchKind.CLIENT_ERROR, url, status=status)
    content_type = resp.headers.get("content-type", "")
    if "xml" not in content_type.lower():
        # GSE's SPA answers unknown paths with HTML 200; never treat that as data.
        return FetchResult(
            FetchKind.UNEXPECTED_CONTENT,
            url,
            status=status,
            detail=f"content-type {content_type!r}",
        )
    return FetchResult(
        FetchKind.OK,
        url,
        status=status,
        body=resp.content,
        etag=resp.headers.get("etag"),
        last_modified=_parse_http_date(resp.headers.get("last-modified")),
    )


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    base: timedelta = timedelta(seconds=60)
    maximum: timedelta = timedelta(minutes=30)
    retry_after_cap: timedelta = timedelta(hours=1)
    jitter: float = 0.2

    def delay(
        self,
        consecutive_failures: int,
        retry_after: timedelta | None = None,
        rng: random.Random | None = None,
    ) -> timedelta:
        """Exponential backoff with jitter; a server Retry-After is honoured as a floor."""
        n = max(consecutive_failures, 1)
        exp = min(self.base * (2 ** (n - 1)), self.maximum)
        factor = 1 + (rng or random).uniform(-self.jitter, self.jitter)
        delay: timedelta = exp * factor
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.retry_after_cap))
        return delay
