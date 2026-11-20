"""Prepare validated collector periods for the fullscreen map component."""

import json
from datetime import timedelta
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit.components.v1 as components

from balance import BLOCKS
from data import FRESH_WITHIN, SITES

HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'assets'
OUTLINE = json.loads((ASSETS / 'georgia-natural-earth.geojson').read_text(encoding='utf-8'))['geometry']['coordinates']
PLACES = json.loads((ASSETS / 'georgia-natural-earth-places.json').read_text(encoding='utf-8'))
TZ = ZoneInfo('Asia/Tbilisi')
FIELDS = (*BLOCKS, 'import', 'export')
MAP = components.declare_component('system_map', path=str(HERE / 'system_map_frontend'))
# Line-level exchange panels (contract v1, docs/contracts/cross_border_flow_v1.md) stay off until
# source rights and the owner's go-ahead exist (Issue #18). Production never sends a document.
CROSS_BORDER_ENABLED = False


def snapshot_badge(row, now, refresh_failed):
    if row is None:
        return 'unavailable'
    if now - row.period_label_utc > FRESH_WITHIN:
        return 'stale'
    quality = dict(item.split(':', 1) for item in row.quality.split(';') if ':' in item)
    if refresh_failed or row.period_label_utc > now or any(quality.get(block) != 'ACT' for block in BLOCKS):
        return 'unconfirmed'
    return 'recent'


def period_payload(rows, now, refresh_failed):
    periods = []
    for row in rows:
        values = {key: getattr(row, f'{key}_mw') for key in FIELDS}
        values = {key: val if val is not None and isfinite(val) else None for key, val in values.items()}
        terms = [values[key] for key in ('generation', 'import', 'export', 'consumption')]
        residual = None
        if all(term is not None for term in terms):
            generation, imports, exports, load = terms
            residual = generation + imports - exports - load
        quality = dict(item.split(':', 1) for item in row.quality.split(';') if ':' in item)
        periods.append(dict(
            label=row.period_label_local, clock=row.period_label_utc.astimezone(TZ).strftime('%H:%M'),
            time=int(row.period_label_utc.timestamp()), values=values, residual=residual,
            retrieved=row.retrieved_at_utc.astimezone(TZ).strftime('%d.%m.%Y %H:%M:%S'),
            status=snapshot_badge(row, now, refresh_failed), wind_confirmed=quality.get('wind') == 'ACT',
        ))
    return periods


def render(lang, reader, now):
    rows = reader.balance(now - timedelta(hours=24), now, now)
    sites = [
        dict(lon=site.longitude, lat=site.latitude, name=getattr(site, f'name_{lang}'),
             uncertainty=site.coordinate_uncertainty_km)
        for site in SITES if site.coordinates_verified and site.longitude is not None and site.latitude is not None
    ]
    MAP(lang=lang, periods=period_payload(rows, now, bool(getattr(reader, 'balance_error', None))),
        refresh_failed=bool(getattr(reader, 'balance_error', None)), cross_border=None,
        outline=OUTLINE, cities=PLACES, sites=sites, key='immersive-system-map')
