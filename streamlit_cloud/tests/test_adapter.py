import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'streamlit_cloud'))
from data import SourceCache, generation_state, weather_state
from app.ingestion.openmeteo import FORECAST, parse_response

FIXTURES = ROOT / 'backend/tests/fixtures'
ACT = (FIXTURES / 'gse/real_act_15112026_0009.xml').read_bytes()
FORECAST_BODY = (FIXTURES / 'openmeteo/real_forecast_icon_global_3sites.json').read_bytes()
META = (FIXTURES / 'openmeteo/real_meta_dwd_icon_before.json').read_bytes()
NOW = datetime(2026, 11, 14, 20, 11, tzinfo=UTC)


def transport(gse=ACT):
    def handler(request):
        if request.url.host == 'admin.gse.com.ge':
            return httpx.Response(200, content=gse, headers={'content-type': 'application/xml'})
        if request.url.path.endswith('meta.json'):
            return httpx.Response(200, content=META, headers={'content-type': 'application/json'})
        return httpx.Response(200, content=FORECAST_BODY, headers={'content-type': 'application/json'})
    return httpx.MockTransport(handler)


def test_shared_cadence_and_copy_isolation():
    cache = SourceCache(transport())
    first = cache.snapshot(NOW)
    assert len(first['history']) == 1
    assert generation_state(first['history'][-1], NOW) == 'fresh'
    first['history'].clear()
    second = cache.snapshot(NOW + timedelta(seconds=60))
    assert len(second['history']) == 1
    assert second['checked'] == first['checked']


def test_midnight_source_label_is_utc():
    cache = SourceCache(transport())
    value = cache.snapshot(NOW)['history'][0]
    assert value['time'] == datetime(2026, 11, 14, 20, 9, tzinfo=UTC)


@pytest.mark.parametrize('quality,expected', [('ACT', 'fresh'), ('NRE', 'unverified')])
def test_quality(quality, expected):
    cache = SourceCache(transport(ACT.replace(b"QUALITY='ACT'", f"QUALITY='{quality}'".encode())))
    item = cache.snapshot(NOW)['history'][0]
    assert generation_state(item, NOW) == expected


def test_zero_and_stale():
    cache = SourceCache(transport(ACT.replace(b"VALUE='73.599297'", b"VALUE='0'")))
    item = cache.snapshot(NOW)['history'][0]
    assert item['value_mw'] == 0
    assert generation_state(item, NOW + timedelta(minutes=12)) == 'stale'


def test_wrong_label_rejected():
    cache = SourceCache(transport(ACT.replace(b'00:09:00', b'00:12:00')))
    result = cache.snapshot(NOW)
    assert not result['history']
    assert result['errors']['gse'] == 'source_timestamp_mismatch'


def test_429_respects_retry_after_and_retains_old_data():
    cache = SourceCache(transport())
    old = cache.snapshot(NOW)['history']
    cache.transport = httpx.MockTransport(lambda r: httpx.Response(429, headers={'Retry-After': '1800'}))
    result = cache.snapshot(NOW + timedelta(minutes=3))
    assert result['history'] == old
    assert cache.next_due['gse'] >= NOW + timedelta(minutes=33)


def test_weather_model_rollover_discarded():
    meta_count = 0
    def handler(request):
        nonlocal meta_count
        if request.url.host == 'admin.gse.com.ge':
            return httpx.Response(404)
        if request.url.path.endswith('meta.json'):
            meta_count += 1
            payload = json.loads(META)
            if meta_count == 2:
                payload['last_run_initialisation_time'] += 3600
            return httpx.Response(200, json=payload)
        return httpx.Response(200, content=FORECAST_BODY, headers={'content-type': 'application/json'})
    result = SourceCache(httpx.MockTransport(handler)).snapshot(NOW)
    assert result['forecast'] is None
    assert result['errors']['forecast'] == 'model_run_changed_during_fetch'


def test_hourly_gap_reduces_coverage():
    series = parse_response(FORECAST_BODY, 3, FORECAST.heights)
    now = series[0].by_height[80][0].valid_at
    packet = dict(series=series, run=now)
    assert weather_state(packet, now, 0, 80)[1] >= 24
    del series[0].by_height[80][5]
    assert weather_state(packet, now, 0, 80) == ('stale', 4)
    series[0].by_height[80][0] = type(series[0].by_height[80][0])(now, None, None)
    assert weather_state(packet, now, 0, 80) == ('unavailable', 0)


def test_forecast_old_run_is_stale():
    series = parse_response(FORECAST_BODY, 3, FORECAST.heights)
    now = series[0].by_height[80][0].valid_at
    assert weather_state(dict(series=series, run=now - timedelta(hours=13)), now, 0, 80)[0] == 'stale'


@pytest.mark.parametrize('lang', ['ქართული', 'English'])
def test_all_pages_render_without_network(lang):
    from streamlit.testing.v1 import AppTest
    cache = SourceCache(transport())
    snapshot = cache.snapshot(NOW)
    archive = (FIXTURES / 'openmeteo/real_archive_era5_3sites_20261106.json').read_bytes()
    snapshot['archive'] = dict(series=parse_response(archive, 3, (10, 100)), retrieved=NOW)
    with patch('data.SourceCache.snapshot', return_value=copy.deepcopy(snapshot)):
        at = AppTest.from_file(str(ROOT / 'streamlit_cloud/app.py')).run(timeout=20)
        at.sidebar.radio[0].set_value(lang).run()
        for name in at.sidebar.radio[1].options:
            at.sidebar.radio[1].set_value(name).run()
            assert not at.exception, str(at.exception)


def test_empty_error_ui():
    from streamlit.testing.v1 import AppTest
    snapshot = dict(history=[], forecast=None, archive=None, errors={'gse': 'timeout'}, checked={}, started=NOW)
    with patch('data.SourceCache.snapshot', return_value=snapshot):
        at = AppTest.from_file(str(ROOT / 'streamlit_cloud/app.py')).run(timeout=20)
        assert not at.exception
        assert at.warning
        assert at.metric[0].value == '-'


def test_late_publication_retried_at_next_tick():
    calls = {}
    def handler(request):
        if request.url.host != 'admin.gse.com.ge':
            return httpx.Response(404)
        path = request.url.path
        calls[path] = calls.get(path, 0) + 1
        if '0009.XML' in path and calls[path] >= 2:
            return httpx.Response(200, content=ACT, headers={'content-type': 'application/xml'})
        return httpx.Response(404)
    cache = SourceCache(httpx.MockTransport(handler))
    first = cache.snapshot(NOW)
    assert not first['history']
    second = cache.snapshot(NOW + timedelta(seconds=180))
    assert second['history'][0]['time'] == datetime(2026, 11, 14, 20, 9, tzinfo=UTC)
    before = dict(calls)
    cache.snapshot(NOW + timedelta(seconds=200))
    assert calls == before


def test_archive_duplicate_times_rejected():
    body = json.loads((FIXTURES / 'openmeteo/real_archive_era5_3sites_20261106.json').read_bytes())
    body[0]['hourly']['time'][1] = body[0]['hourly']['time'][0]
    cache = SourceCache(httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    cache.poll('era5', NOW, timedelta(days=1), cache.reanalysis)
    assert cache.archive is None
    assert cache.errors['era5'] == 'invalid_weather_time_axis'


def test_bad_archive_retains_prior_payload():
    cache = SourceCache()
    cache.archive = {'sentinel': True}
    body = json.loads((FIXTURES / 'openmeteo/real_archive_era5_3sites_20261106.json').read_bytes())
    body[0]['hourly']['time'][0] += 60
    cache.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    cache.poll('era5', NOW, timedelta(days=1), cache.reanalysis)
    assert cache.archive == {'sentinel': True}
    assert cache.errors['era5'] == 'invalid_weather_time_axis'


def test_history_uses_elapsed_time_not_categories():
    from streamlit.testing.v1 import AppTest
    cache = SourceCache(transport())
    snapshot = cache.snapshot(NOW)
    later = dict(snapshot['history'][0])
    later['time'] += timedelta(hours=3)
    snapshot['history'].append(later)
    with patch('data.SourceCache.snapshot', return_value=snapshot):
        at = AppTest.from_file(str(ROOT / 'streamlit_cloud/app.py')).run()
        at.sidebar.radio[1].set_value('ისტორია').run()
        chart = json.loads(at.get('plotly_chart')[0].proto.spec)
        assert chart['layout']['xaxis']['type'] == 'date'
        x = chart['data'][0]['x']
        assert datetime.fromisoformat(x[1]) - datetime.fromisoformat(x[0]) == timedelta(hours=3)
        assert x[0].startswith('2026-11-15T00:09')
