"""One GSE national balance period and an offline geographic reference map."""

import json
from datetime import timedelta
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

import pydeck as pdk
import streamlit as st

import ui
from balance import BLOCKS
from data import FRESH_WITHIN, SITES
from i18n import tr
from sitemap import TOOLTIP_STYLE

TZ = ZoneInfo('Asia/Tbilisi')
ASSETS = Path(__file__).parent / 'assets'
OUTLINE = json.loads((ASSETS / 'georgia-natural-earth.geojson').read_text(encoding='utf-8'))
PLACES = json.loads((ASSETS / 'georgia-natural-earth-places.json').read_text(encoding='utf-8'))
DOCS = 'https://github.com/GiorgiKhorbaladze/Georgia-WindCast/blob/main/docs/sources'
METRICS = (
    ('consumption_mw', 'consumption'),
    ('generation_mw', 'snapshot_generation'),
    ('import_mw', 'src_import'),
    ('export_mw', 'src_export'),
    ('hydro_mw', 'src_hydro'),
    ('thermal_mw', 'src_thermal'),
    ('wind_mw', 'src_wind'),
    ('solar_mw', 'src_solar'),
)
CSS = """
<style>
.st-key-snapshot-totals .wc-grid, .st-key-snapshot-mix .wc-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0; gap: .65rem;
}
.st-key-snapshot-totals .wc-card { background: linear-gradient(150deg, #12283a, #0d1a28); }
.st-key-snapshot-mix .wc-card { min-height: 0; padding-block: .7rem; }
.st-key-snapshot-mix .wc-value { font-size: 1.25rem; }
.st-key-snapshot-map [data-testid="stDeckGlJsonChart"] { border-radius: 12px; overflow: hidden; background: #0a1723; }
@media (max-width: 760px) {
  .st-key-snapshot-totals .wc-grid, .st-key-snapshot-mix .wc-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .st-key-snapshot-totals .wc-card, .st-key-snapshot-mix .wc-card { padding: .65rem .75rem; min-height: 0; }
}
</style>
"""


def snapshot_badge(row, now, refresh_failed):
    if row is None:
        return 'st_unavailable', 'unavailable'
    if now - row.period_label_utc > FRESH_WITHIN:
        return 'st_stale', 'stale'
    quality = dict(item.split(':', 1) for item in row.quality.split(';') if ':' in item)
    if refresh_failed or row.period_label_utc > now or any(quality.get(block) != 'ACT' for block in BLOCKS):
        return 'snapshot_uncertain', 'unverified'
    return 'snapshot_recent', 'fresh'


def render(lang, reader, now):
    rows = reader.balance(now - timedelta(hours=24), now, now)
    row = rows[-1] if rows else None
    refresh_failed = bool(getattr(reader, 'balance_error', None))
    label, state = snapshot_badge(row, now, refresh_failed)

    st.markdown(CSS, unsafe_allow_html=True)
    ui.hero(tr('snapshot_title', lang), tr('snapshot_average', lang), ui.badge(tr(label, lang), state))
    if refresh_failed:
        st.warning(tr('snapshot_refresh_error', lang))
    if row is None:
        st.info(tr('snapshot_empty', lang))
    else:
        retrieved = row.retrieved_at_utc.astimezone(TZ).strftime('%d.%m.%Y %H:%M:%S')
        st.caption(f"**{tr('snapshot_source_time', lang)}** · {row.period_label_local} (UTC+4)  |  "
                   f"**{tr('retrieved', lang)}** · {retrieved} (UTC+4)")

    cards = []
    for field, key in METRICS:
        value = getattr(row, field, None)
        available = value is not None and isfinite(value)
        cards.append(ui.card(tr(key, lang), ui.fmt(value, 2) if available else '—',
                             'MW' if available else '', '' if available else tr('st_unavailable', lang),
                             accent=field in ('consumption_mw', 'generation_mw')))
    with st.container(key='snapshot-totals'):
        ui.cards(cards[:4])
    with st.container(key='snapshot-mix'):
        st.markdown(f"**{tr('snapshot_mix', lang)}**")
        ui.cards(cards[4:])
    if row is not None and (row.import_mw is None or row.export_mw is None):
        st.caption(tr('snapshot_flow_note', lang))
    st.caption(f"[{tr('gse_tag', lang)}](https://www.gse.com.ge/) · "
               f"[{tr('snapshot_sources', lang)}]({DOCS}/system-snapshot.md)")
    render_map(lang)


def render_map(lang):
    sites = {site.id: site for site in SITES
             if site.coordinates_verified and site.longitude is not None and site.latitude is not None}
    names = {key: getattr(site, f'name_{lang}') for key, site in sites.items()}
    st.subheader(tr('snapshot_map_title', lang))
    st.caption(tr('snapshot_map_scope', lang))
    with st.container(border=True, key='snapshot-map'):
        map_panel, controls = st.columns([3, 1.4], gap='medium')
        with controls:
            focus = st.selectbox(tr('snapshot_focus', lang), [None, *sites],
                                 format_func=lambda key: names[key] if key else tr('snapshot_country', lang),
                                 key='snapshot-focus')
            with st.expander(tr('snapshot_layers', lang), expanded=True):
                border = st.checkbox(tr('snapshot_border', lang), value=True, key='snapshot-border')
                places = st.checkbox(tr('snapshot_places', lang), value=True, key='snapshot-places')
                wind = st.checkbox(tr('snapshot_wind', lang), value=True, key='snapshot-wind')
            if focus:
                site = sites[focus]
                st.markdown(f"**{names[focus]}**")
                st.caption(f"{getattr(site, f'municipality_{lang}')} · {site.latitude:.4f}°, {site.longitude:.4f}°")
                st.caption(tr('snapshot_accuracy', lang, km=site.coordinate_uncertainty_km))
                st.caption(f"[{tr('snapshot_sources', lang)}]({DOCS}/sites.md)")
        with map_panel:
            layers = []
            if border:
                layers.append(pdk.Layer(
                    'GeoJsonLayer', id='country-outline', data=OUTLINE, get_fill_color=[18, 41, 57],
                    get_line_color=[107, 148, 170], line_width_min_pixels=1.25))
            if places:
                labels = [dict(name=p[lang], lon=p['lon'], lat=p['lat']) for p in PLACES]
                # A tuple keeps pydeck from treating the glyphs as accessor expressions.
                layers.append(pdk.Layer(
                    'TextLayer', id='reference-cities', data=labels, get_position='[lon, lat]',
                    get_text='name', get_size=12, get_color=[175, 198, 214], font_family="'sans-serif'",
                    character_set=tuple(sorted(set(''.join(p['name'] for p in labels)))), get_pixel_offset=[0, 9]))
            if wind:
                records = [dict(name=names[key], lon=site.longitude, lat=site.latitude,
                                color=[234, 252, 248] if key == focus else [45, 212, 191])
                           for key, site in sites.items()]
                layers.append(pdk.Layer(
                    'ScatterplotLayer', id='verified-wind-sites', data=records, get_position='[lon, lat]',
                    get_radius=850, radius_min_pixels=5, radius_max_pixels=10, get_fill_color='color',
                    get_line_color=[7, 17, 28], stroked=True, line_width_min_pixels=1.5, pickable=True))
            view = pdk.ViewState(latitude=42.2, longitude=43.4, zoom=5)
            if focus:
                site = sites[focus]
                view = pdk.ViewState(latitude=site.latitude, longitude=site.longitude, zoom=9)
            st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view,
                                    tooltip={'text': '{name}', 'style': TOOLTIP_STYLE},
                                    map_provider=None, map_style=None),
                             height=365, key=f'snapshot-deck-{focus}', alt=tr('snapshot_map_scope', lang))
            ui.note(tr('snapshot_outline', lang), ui.tag(tr('snapshot_wind', lang), 'off') if wind else '')
