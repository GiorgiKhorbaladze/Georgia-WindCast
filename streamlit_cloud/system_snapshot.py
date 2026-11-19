"""Display one national GSE balance period beside verified wind farm locations."""

import json
from datetime import timedelta
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

import pydeck as pdk
import streamlit as st

import ui
from data import FRESH_WITHIN, SITES
from i18n import tr
from sitemap import TOOLTIP_STYLE

TZ = ZoneInfo('Asia/Tbilisi')
OUTLINE = json.loads((Path(__file__).parent / 'assets/georgia-natural-earth.geojson').read_text(encoding='utf-8'))
DOCS = 'https://github.com/GiorgiKhorbaladze/Georgia-WindCast/blob/main/docs/sources'
METRICS = (
    ('consumption_mw', 'consumption', 'MW'),
    ('generation_mw', 'bal_gen_now', 'MW'),
    ('hydro_mw', 'src_hydro', 'MW'),
    ('thermal_mw', 'src_thermal', 'MW'),
    ('wind_mw', 'src_wind', 'MW'),
    ('solar_mw', 'src_solar', 'MW'),
    ('import_mw', 'src_import', 'MW'),
    ('export_mw', 'src_export', 'MW'),
    ('frequency_hz', 'snapshot_frequency', 'Hz'),
)


def render(lang, reader, now):
    rows = reader.balance(now - timedelta(hours=24), now, now)
    row = rows[-1] if rows else None
    state = 'unavailable'
    label = 'st_unavailable'
    if row is not None:
        state, label = ('stale', 'st_stale') if now - row.period_label_utc > FRESH_WITHIN else ('fresh', 'snapshot_recent')

    ui.hero(tr('snapshot_title', lang), tr('snapshot_average', lang), ui.badge(tr(label, lang), state))
    st.caption(f"[{tr('gse_tag', lang)}](https://www.gse.com.ge/) · "
               f"[{tr('snapshot_sources', lang)}]({DOCS}/system-snapshot.md)")
    if getattr(reader, 'balance_error', None):
        st.warning(tr('snapshot_refresh_error', lang))
    if row is None:
        st.info(tr('snapshot_empty', lang))
    else:
        retrieved = row.retrieved_at_utc.astimezone(TZ).strftime('%d.%m.%Y %H:%M:%S')
        st.caption(f"{tr('snapshot_source_time', lang)} · {row.period_label_local} (UTC+4)  |  "
                   f"{tr('retrieved', lang)} · {retrieved} (UTC+4)")

    cards = []
    for field, key, unit in METRICS:
        value = getattr(row, field, None)
        available = value is not None and isfinite(value)
        cards.append(ui.card(tr(key, lang), ui.fmt(value, 2) if available else '—',
                             unit if available else '', '' if available else tr('st_unavailable', lang),
                             accent=field == 'consumption_mw'))
    with st.container(key='system-snapshot-cards'):
        st.markdown(
            '<style>@media (max-width: 640px) { .st-key-system-snapshot-cards .wc-grid '
            '{ grid-template-columns: repeat(auto-fit, minmax(min(100%, 145px), 1fr)); } }</style>',
            unsafe_allow_html=True,
        )
        ui.cards(cards)
    if row is not None and (row.import_mw is None or row.export_mw is None):
        st.caption(tr('snapshot_flow_note', lang))
    render_map(lang)


def render_map(lang):
    st.subheader(tr('snapshot_map_title', lang))
    st.caption(tr('snapshot_map_scope', lang))
    records = [
        dict(name=site.name_ka if lang == 'ka' else site.name_en, lon=site.longitude, lat=site.latitude)
        for site in SITES if site.coordinates_verified and site.longitude is not None and site.latitude is not None
    ]
    layer = pdk.Layer(
        'ScatterplotLayer', data=records, get_position='[lon, lat]', get_radius=900,
        radius_min_pixels=4, get_fill_color=[45, 212, 191, 235], get_line_color=[7, 17, 28],
        stroked=True, line_width_min_pixels=2, pickable=True,
    )
    outline = pdk.Layer('GeoJsonLayer', data=OUTLINE, get_fill_color=[19, 38, 54],
                        get_line_color=[108, 139, 158], line_width_min_pixels=1)
    view = pdk.ViewState(latitude=42.1, longitude=43.45, zoom=5.25)
    st.pydeck_chart(pdk.Deck(layers=[outline, layer], initial_view_state=view,
                            tooltip={'text': '{name}', 'style': TOOLTIP_STYLE},
                            map_provider=None, map_style=None), height=320)
    st.caption(tr('snapshot_outline', lang))
    st.caption(' · '.join(r['name'] for r in records) + f" · [{tr('snapshot_sources', lang)}]({DOCS}/sites.md)")
