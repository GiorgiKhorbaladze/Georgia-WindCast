import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ingestion.http_policy import BackoffPolicy, FetchKind, fetch, parse_retry_after
from tests.gse_fixtures import REAL_ACT

URL = "https://example.invalid/fact/file.XML"


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ok_xml():
    def h(_req):
        return httpx.Response(
            200,
            content=REAL_ACT,
            headers={
                "content-type": "text/xml",
                "etag": '"abc"',
                "last-modified": "Sat, 14 Nov 2026 20:10:17 GMT",
            },
        )

    r = fetch(client_for(h), URL)
    assert r.kind is FetchKind.OK and not r.is_failure
    assert r.etag == '"abc"'
    assert r.last_modified == datetime(2026, 11, 14, 20, 10, 17, tzinfo=UTC)
    assert r.body == REAL_ACT


def test_html_200_is_unexpected_content():
    r = fetch(
        client_for(
            lambda _r: httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
        ),
        URL,
    )
    assert r.kind is FetchKind.UNEXPECTED_CONTENT and r.is_failure


def test_404_is_not_a_failure():
    r = fetch(client_for(lambda _r: httpx.Response(404)), URL)
    assert r.kind is FetchKind.NOT_PUBLISHED and not r.is_failure


def test_429_retry_after_seconds():
    r = fetch(client_for(lambda _r: httpx.Response(429, headers={"retry-after": "120"})), URL)
    assert r.kind is FetchKind.RATE_LIMITED and r.retry_after == timedelta(seconds=120)


def test_503_retry_after_http_date():
    later = "Sat, 14 Nov 2026 21:00:00 GMT"
    r = fetch(client_for(lambda _r: httpx.Response(503, headers={"retry-after": later})), URL)
    assert r.kind is FetchKind.SERVER_ERROR and r.retry_after is not None


@pytest.mark.parametrize("status", [500, 502, 504])
def test_5xx(status):
    assert fetch(client_for(lambda _r: httpx.Response(status)), URL).kind is FetchKind.SERVER_ERROR


def test_403_is_client_error():
    assert fetch(client_for(lambda _r: httpx.Response(403)), URL).kind is FetchKind.CLIENT_ERROR


def test_timeout():
    def h(req):
        raise httpx.ReadTimeout("slow", request=req)

    assert fetch(client_for(h), URL).kind is FetchKind.TIMEOUT


def test_network_error():
    def h(req):
        raise httpx.ConnectError("refused", request=req)

    assert fetch(client_for(h), URL).kind is FetchKind.NETWORK_ERROR


def test_parse_retry_after_variants():
    now = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
    assert parse_retry_after("30", now) == timedelta(seconds=30)
    assert parse_retry_after("Sat, 14 Nov 2026 20:05:00 GMT", now) == timedelta(minutes=5)
    assert parse_retry_after("Sat, 14 Nov 2026 19:00:00 GMT", now) == timedelta(0)
    assert parse_retry_after("soon", now) is None
    assert parse_retry_after(None, now) is None
    assert parse_retry_after("-5", now) is None


def test_backoff_grows_caps_and_honours_retry_after():
    p = BackoffPolicy(base=timedelta(seconds=60), maximum=timedelta(minutes=30), jitter=0.0)
    assert p.delay(1) == timedelta(seconds=60)
    assert p.delay(2) == timedelta(seconds=120)
    assert p.delay(10) == timedelta(minutes=30)
    assert p.delay(1, retry_after=timedelta(minutes=10)) == timedelta(minutes=10)
    assert p.delay(1, retry_after=timedelta(days=2)) == timedelta(hours=1)  # capped


def test_backoff_jitter_bounded():
    p = BackoffPolicy(base=timedelta(seconds=100), jitter=0.2)
    rng = random.Random(1)
    for _ in range(200):
        d = p.delay(1, rng=rng).total_seconds()
        assert 80 <= d <= 120
