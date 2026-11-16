"""On-demand, shared, bounded source cache. No background collector or durable archive."""
from __future__ import annotations

import copy
import hashlib
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.ingestion.gse_parser import export_file_name, parse_wind_export
from app.ingestion.http_policy import BackoffPolicy, FetchKind, fetch
from app.ingestion.openmeteo import (
    FORECAST, REANALYSIS, archive_url, forecast_url, meta_url, parse_response, parse_run_time,
)
from app.sites import SITES

GSE_BASE = 'https://admin.gse.com.ge/storage/uploads/fact/'
WEATHER_BASE = 'https://api.open-meteo.com'
ARCHIVE_BASE = 'https://archive-api.open-meteo.com'


def generation_state(reading, now):
    if reading is None:
        return 'unavailable'
    if reading['quality'] != 'ACT':
        return 'unverified'
    age = (now - reading['time']).total_seconds()
    return 'fresh' if 0 <= age <= 600 else 'stale'


def weather_state(packet, now, site_index, height):
    if packet is None:
        return 'unavailable', 0
    values = packet['series'][site_index].by_height[height]
    expected = now.replace(minute=0, second=0, microsecond=0)
    by_time = {v.valid_at: v for v in values}
    hours = 0
    for offset in range(73):
        value = by_time.get(expected + timedelta(hours=offset))
        if value is None or value.speed_ms is None or value.direction_deg is None:
            break
        hours += 1
    coverage = max(0, hours - 1)
    if not hours:
        return 'unavailable', 0
    if (now - packet['run']).total_seconds() > 43200 or coverage < 24:
        return 'stale', coverage
    return 'fresh', coverage


class SourceCache:
    def __init__(self, transport=None):
        self.lock = threading.RLock()
        self.transport = transport
        self.history = {}
        self.started = datetime.now(UTC)
        self.forecast = None
        self.archive = None
        self.checked = {}
        self.next_due = {}
        self.failures = {}
        self.errors = {}
        self.requested_labels = {}

    def client(self):
        return httpx.Client(timeout=10, follow_redirects=False, transport=self.transport,
                            headers={'User-Agent': 'Georgia-WindCast/Streamlit (informational)'})

    def get(self, client, url, kind):
        result = fetch(client, url, expect=kind)
        if result.kind != FetchKind.OK:
            raise SourceError(result.kind.value, result.retry_after)
        return result.body

    def poll(self, name, now, interval, operation):
        if now < self.next_due.get(name, datetime.min.replace(tzinfo=UTC)):
            return
        self.checked[name] = now
        self.next_due[name] = now + interval
        try:
            with self.client() as client:
                operation(client, now)
            self.errors.pop(name, None)
            self.failures[name] = 0
        except (ValueError, TypeError, KeyError, OverflowError, OSError, httpx.HTTPError) as exc:
            self.failures[name] = min(self.failures.get(name, 0) + 1, 10)
            delay = BackoffPolicy().delay(self.failures[name], getattr(exc, 'retry_after', None))
            # Never shorten either the source cadence or Retry-After.
            self.next_due[name] = max(self.next_due[name], now + delay)
            self.errors[name] = getattr(exc, 'code', 'invalid_source_response')

    def generation(self, client, now):
        due = (now - timedelta(seconds=75)).replace(second=0, microsecond=0)
        due -= timedelta(minutes=due.minute % 3)
        for offset in range(3):
            label = due - timedelta(minutes=3 * offset)
            if label in self.history:
                continue
            attempt = self.requested_labels.get(label)
            if attempt and (attempt['count'] >= 3 or now < attempt['next_due']):
                continue
            self.requested_labels[label] = dict(count=(attempt['count'] if attempt else 0) + 1,
                                                 next_due=now + timedelta(seconds=180))
            url = GSE_BASE + export_file_name(label)
            result = fetch(client, url)
            if result.kind == FetchKind.NOT_PUBLISHED:
                continue
            if result.kind != FetchKind.OK:
                raise SourceError(result.kind.value, result.retry_after)
            reading = parse_wind_export(result.body)
            if reading.period_label_utc != label or reading.period_label_utc > now:
                raise SourceError('source_timestamp_mismatch')
            self.history[label] = dict(time=label, value_mw=reading.value_mw,
                                       quality=reading.quality, retrieved=now, url=url,
                                       sha256=hashlib.sha256(result.body).hexdigest())
            break
        cutoff = now - timedelta(days=7)
        self.history = {k: v for k, v in self.history.items() if k >= cutoff}
        self.requested_labels = {k: v for k, v in self.requested_labels.items() if k >= cutoff}

    def weather(self, client, now):
        metadata_url = meta_url(WEATHER_BASE, FORECAST.meta_model)
        run = parse_run_time(self.get(client, metadata_url, 'json'))
        if run > now:
            raise SourceError('future_model_run')
        if self.forecast is not None and run < self.forecast['run']:
            raise SourceError('model_run_regressed')
        if self.forecast is not None and self.forecast['run'] == run:
            return
        url = forecast_url(WEATHER_BASE, SITES, 4)
        body = self.get(client, url, 'json')
        series = parse_response(body, len(SITES), FORECAST.heights)
        after = parse_run_time(self.get(client, metadata_url, 'json'))
        if after != run:
            raise SourceError('model_run_changed_during_fetch')
        for location in series:
            for height, values in location.by_height.items():
                stamps = [v.valid_at for v in values]
                if len(stamps) != len(set(stamps)) or stamps != sorted(stamps) or any(t.minute or t.second or t.microsecond for t in stamps):
                    raise SourceError('invalid_weather_time_axis')
                location.by_height[height] = [v for v in values if v.valid_at >= run]
        self.forecast = dict(run=run, retrieved=now, series=series, url=url,
                             sha256=hashlib.sha256(body).hexdigest())

    def reanalysis(self, client, now):
        end = (now - timedelta(days=5)).date()
        start = end - timedelta(days=6)
        url = archive_url(ARCHIVE_BASE, SITES, str(start), str(end))
        body = self.get(client, url, 'json')
        series = parse_response(body, len(SITES), REANALYSIS.heights)
        for location in series:
            for values in location.by_height.values():
                stamps = [v.valid_at for v in values]
                if len(stamps) != len(set(stamps)) or stamps != sorted(stamps) or any(t.minute or t.second or t.microsecond for t in stamps):
                    raise SourceError('invalid_weather_time_axis')
        self.archive = dict(retrieved=now, series=series, url=url,
                            sha256=hashlib.sha256(body).hexdigest())

    def snapshot(self, now=None, include_archive=False):
        now = now or datetime.now(UTC)
        with self.lock:
            self.poll('gse', now, timedelta(seconds=180), self.generation)
            self.poll('forecast', now, timedelta(minutes=15), self.weather)
            if include_archive:
                self.poll('era5', now, timedelta(days=1), self.reanalysis)
            return copy.deepcopy(dict(history=sorted(self.history.values(), key=lambda x: x['time']),
                                      forecast=self.forecast, archive=self.archive,
                                      errors=self.errors, checked=self.checked, started=self.started))


class SourceError(ValueError):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)
