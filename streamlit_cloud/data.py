"""Shared, bounded live source cache for the app (open pages only).

Durable history comes from the scheduled collector (collector.py -> ``data`` branch, read by
history.py). This cache only fills the minutes since the collector's last run and serves the
weather products; it is not an archive.
"""
from __future__ import annotations

import copy
import hashlib
import os
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

# Backend first: this directory's app.py (the Streamlit entrypoint) must not shadow backend/app.
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


def utcnow():
    """Single clock for the app (patched in tests)."""
    return datetime.now(UTC)


FRESH_WITHIN = timedelta(seconds=600)
LIVE_LOOKBACK_PERIODS = 20  # last hour; older periods come from the collector
LIVE_MAX_REQUESTS = 4  # per poll, newest first
LIVE_RETENTION = timedelta(days=2)


def generation_state(reading, now):
    """Production rules (backend/app/api/v1.py): age from the source label first, then quality.

    stale beats unverified, so an old non-ACT value is never reported as merely "unverified";
    a label ahead of this clock (accepted skew) is unverified, never fresh.
    """
    if reading is None:
        return 'unavailable'
    if now - reading['time'] > FRESH_WITHIN:
        return 'stale'
    if reading['time'] > now or reading['quality'] != 'ACT':
        return 'unverified'
    return 'fresh'


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
        # No User-Agent override by default (same as the production worker); an operator may set
        # WINDCAST_USER_AGENT to identify the deployment to the providers.
        headers = {'User-Agent': ua} if (ua := os.environ.get('WINDCAST_USER_AGENT')) else {}
        return httpx.Client(timeout=10, follow_redirects=False, transport=self.transport,
                            headers=headers)

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
        requests = 0
        for offset in range(LIVE_LOOKBACK_PERIODS):
            if requests >= LIVE_MAX_REQUESTS:
                break
            label = due - timedelta(minutes=3 * offset)
            if label in self.history:
                continue
            attempt = self.requested_labels.get(label)
            if attempt and (attempt['count'] >= 3 or now < attempt['next_due']):
                continue
            self.requested_labels[label] = dict(count=(attempt['count'] if attempt else 0) + 1,
                                                 next_due=now + timedelta(seconds=180))
            url = GSE_BASE + export_file_name(label)
            requests += 1
            result = fetch(client, url)
            if result.kind == FetchKind.NOT_PUBLISHED:
                continue
            if result.kind != FetchKind.OK:
                raise SourceError(result.kind.value, result.retry_after)
            reading = parse_wind_export(result.body)
            if reading.period_label_utc != label or reading.period_label_utc > now + timedelta(seconds=60):
                raise SourceError('source_timestamp_mismatch')
            self.history[label] = dict(time=label, value_mw=reading.value_mw,
                                       quality=reading.quality, retrieved=now, url=url,
                                       sha256=hashlib.sha256(result.body).hexdigest())
        cutoff = now - LIVE_RETENTION
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
            return  # same run already held (live or from the collector's stored copy)
        url = forecast_url(WEATHER_BASE, SITES, 4)
        body = self.get(client, url, 'json')
        after = parse_run_time(self.get(client, metadata_url, 'json'))
        if after != run:
            raise SourceError('model_run_changed_during_fetch')
        self.forecast = forecast_packet(body, run, now, url, 'live')

    def reanalysis(self, client, now):
        url = era5_url(now)
        self.archive = archive_packet(self.get(client, url, 'json'), now, url, 'live')

    def adopt_stored(self, forecast=None, archive=None):
        """Use the collector's stored copies when they are newer than (or replace missing) live data."""
        with self.lock:
            if forecast is not None and (self.forecast is None or forecast['run'] > self.forecast['run']):
                self.forecast = forecast
            if archive is not None and (self.archive is None or archive['retrieved'] > self.archive['retrieved']):
                self.archive = archive

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


def _check_axis(series):
    for location in series:
        for values in location.by_height.values():
            stamps = [v.valid_at for v in values]
            if (len(stamps) != len(set(stamps)) or stamps != sorted(stamps)
                    or any(t.minute or t.second or t.microsecond for t in stamps)):
                raise SourceError('invalid_weather_time_axis')


def forecast_packet(body, run, retrieved, url, origin):
    """Strictly parsed forecast; hours before the model run are dropped (not part of the run)."""
    series = parse_response(body, len(SITES), FORECAST.heights)
    _check_axis(series)
    for location in series:
        for height, values in location.by_height.items():
            location.by_height[height] = [v for v in values if v.valid_at >= run]
    return dict(run=run, retrieved=retrieved, series=series, url=url, origin=origin,
                sha256=hashlib.sha256(body).hexdigest())


HIST_FORECAST_BASE = 'https://historical-forecast-api.open-meteo.com'


def hist_forecast_url(start, end):
    """Past ICON forecasts (Open-Meteo historical forecast archive), same variables as the live one."""
    from urllib.parse import urlencode
    lats = ','.join(f'{s.latitude:.6f}' for s in SITES)
    lons = ','.join(f'{s.longitude:.6f}' for s in SITES)
    hourly = ','.join(f'wind_{k}_{h}m' for h in FORECAST.heights for k in ('speed', 'direction'))
    params = dict(latitude=lats, longitude=lons, hourly=hourly, models=FORECAST.model,
                  start_date=str(start), end_date=str(end), wind_speed_unit='ms',
                  timeformat='unixtime', timezone='GMT')
    return f"{HIST_FORECAST_BASE}/v1/forecast?{urlencode(params, safe=',')}"


def hist_forecast_packet(body, retrieved, url):
    series = parse_response(body, len(SITES), FORECAST.heights)
    _check_axis(series)
    return dict(series=series, retrieved=retrieved, url=url, sha256=hashlib.sha256(body).hexdigest())


def era5_url(now):
    end = (now - timedelta(days=5)).date()
    return archive_url(ARCHIVE_BASE, SITES, str(end - timedelta(days=6)), str(end))


def archive_packet(body, retrieved, url, origin):
    series = parse_response(body, len(SITES), REANALYSIS.heights)
    _check_axis(series)
    return dict(retrieved=retrieved, series=series, url=url, origin=origin,
                sha256=hashlib.sha256(body).hexdigest())


class SourceError(ValueError):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)
