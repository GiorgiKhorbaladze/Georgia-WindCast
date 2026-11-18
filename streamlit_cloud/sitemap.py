"""Site map content: per-site model wind as text and as an arrow. Pure functions, no Streamlit.

Convention (same as compass.py): the text gives where the wind blows FROM; the arrow shows where
the air moves TO (FROM + 180°). Only the model value for the site and hour is used: no spatial
interpolation, no invented field. A missing value gets no arrow and an explicit "unavailable"
text; light wind (< 3 m/s) gets a muted arrow, because its direction is less meaningful.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from zoneinfo import ZoneInfo

import compass
from i18n import tr

TZ = ZoneInfo('Asia/Tbilisi')
ARROW_PX = 58  # on-screen icon height, constant at every zoom and screen width
ICON_W, ICON_H = 64, 96  # canvas: arrow points UP (north) in the top half; the lower half is empty
# Anchor = bottom centre = the site, so the arrow starts just outside the marker (about 26 px away)
# instead of being hidden under it, and always extends from the site towards where the air moves.
_ARROW = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="96" viewBox="0 0 64 96">'
          '<path d="M32 3 L54 30 L39 30 L39 50 L25 50 L25 30 L10 30 Z" fill="{fill}" '
          'stroke="#07111c" stroke-width="3.5" stroke-linejoin="round"/></svg>')
# Narrow, wrapping tooltip so it stays inside the map on a 320-390 px phone.
TOOLTIP_STYLE = {'maxWidth': '240px', 'whiteSpace': 'pre-wrap', 'fontSize': '12px', 'lineHeight': '1.35',
                 'backgroundColor': '#112236', 'color': '#e8f1f8', 'border': '1px solid #1c3349', 'borderRadius': '8px'}
COLORS = {'wind': '#f8fafc', 'calm': '#8ea4b8'}


def icon(kind: str) -> dict:
    """deck.gl IconLayer icon (inline SVG, no external asset); anchor = tail at the site."""
    svg = _ARROW.format(fill=COLORS[kind]).encode()
    return {'url': 'data:image/svg+xml;base64,' + base64.b64encode(svg).decode(), 'width': ICON_W,
            'height': ICON_H, 'anchorY': ICON_H, 'mask': False}


def icon_angle(to_deg: float) -> float:
    """deck.gl rotates icons counter-clockwise in degrees; a compass bearing turns clockwise."""
    return (360.0 - to_deg) % 360.0


def site_record(num: int, site, value, lang: str, height_m: int = 80) -> dict:
    """Card, tooltip and arrow data for one site from its model value at the current hour."""
    name = site.name_ka if lang == 'ka' else site.name_en
    status = site.status_ka if lang == 'ka' else site.status_en
    speed = getattr(value, 'speed_ms', None)
    direction = getattr(value, 'direction_deg', None)
    ok = value is not None and speed is not None and compass.sector(direction, lang) is not None
    unit = tr('ms', lang)
    when = value.valid_at.astimezone(TZ).strftime('%d.%m %H:%M') if value is not None else '-'
    meta = tr('map_meta', lang, h=height_m, t=when)
    rec = dict(num=str(num), lat=site.latitude, lon=site.longitude, name=name, status=status, meta=meta,
               has_arrow=ok, calm=False, speed_txt='-', dir_txt=tr('map_na', lang), to_txt='', angle=0.0, icon=None)
    if ok:
        calm = speed < compass.CALM_MS
        to = compass.to_bearing(direction)
        rec.update(speed_txt=f'{speed:.1f} {unit}', dir_txt=compass.label(direction, lang), calm=calm,
                   to_txt=tr('map_to', lang, side=compass.towards(to, lang)),
                   angle=icon_angle(to), icon=icon('calm' if calm else 'wind'))
    lines = [name, f"{rec['speed_txt']} · {rec['dir_txt']}" if ok else rec['dir_txt'], meta]
    if ok:
        lines.append(rec['to_txt'])
        if rec['calm']:
            lines.append(tr('calm_hint_map', lang))
    rec['tip'] = '\n'.join(lines)
    return rec


def value_at(packet, index: int, height_m: int, hour):
    """The site's model value for exactly this valid hour, or None (never interpolated)."""
    if not packet:
        return None
    return next((v for v in packet['series'][index].by_height.get(height_m, []) if v.valid_at == hour), None)


def forecast_hours(packet, now, height_m: int = 80, horizon_h: int = 72) -> list:
    """Valid hours of the current run, from the current hour up to `horizon_h` ahead, for which at
    least one site has both speed and direction. Only hours present in the run are returned, so the
    time slider never steps through hours the model did not provide."""
    if not packet:
        return []
    hour = now.replace(minute=0, second=0, microsecond=0)
    last = hour + timedelta(hours=horizon_h)
    hours = set()
    for loc in packet['series']:
        for v in loc.by_height.get(height_m, []):
            if hour <= v.valid_at <= last and v.speed_ms is not None and compass.sector(v.direction_deg) is not None:
                hours.add(v.valid_at)
    return sorted(hours)


def next_hour(hours: list, current, step: int = 1):
    """Next (or previous) available hour, wrapping round at the end of the run."""
    if not hours:
        return None
    i = hours.index(current) if current in hours else -1
    return hours[(i + step) % len(hours)]
