"""Georgia WindCast - Streamlit Community Cloud edition.

Durable GSE history comes from the scheduled collector (collector.py, GitHub Actions -> `data`
branch); the live cache (data.py) fills the minutes since its last run and serves the Open-Meteo
products. Production parsers and freshness rules from backend/app are reused unchanged.
Pages: overview, historical analysis, forecast (model wind + experimental MW estimate), forecast
accuracy, data and methodology. Official GSE data and model estimates are always labelled apart.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analytics as an  # noqa: E402
import compass  # noqa: E402
from charts import now_marker, series_figure, series_frame, time_ticks, wall  # noqa: E402
import data as source  # noqa: E402
import mwmodel  # noqa: E402
import ui  # noqa: E402
import verification as ver  # noqa: E402
from data import FORECAST, REANALYSIS, SITES, SourceCache, generation_state, weather_state  # noqa: E402
from history import DATA_BASE, HistoryReader, collector_age  # noqa: E402
from i18n import tr  # noqa: E402

st.set_page_config(page_title='Georgia WindCast', page_icon='🌬️', layout='wide')
TZ = ZoneInfo('Asia/Tbilisi')
BASEMAP = 'https://tiles.openfreemap.org/styles/dark'  # same basemap as the main product
PAGES = ('overview', 'balance', 'analytics', 'forecast', 'accuracy', 'data')
STATE_KEY = {'fresh': 'st_fresh', 'stale': 'st_stale', 'unavailable': 'st_unavailable', 'unverified': 'st_unverified'}


# Shared objects are cached per code version: on a redeploy Streamlit reloads the modules but keeps
# cache_resource entries, so an instance of the OLD class (without newer methods) would survive and
# raise AttributeError. Keying by the class identity creates a fresh instance after every reload.
@st.cache_resource
def _source_cache(code_version: str):
    return SourceCache()


@st.cache_resource
def _history_reader(code_version: str):
    base = os.environ.get('WINDCAST_DATA_BASE_URL', DATA_BASE)
    return HistoryReader(lambda: httpx.Client(timeout=10, follow_redirects=False), base)


def source_cache():
    return _source_cache(f'{SourceCache.__module__}:{id(SourceCache)}')


def history_reader():
    return _history_reader(f'{HistoryReader.__module__}:{id(HistoryReader)}')


AUTHOR_LINKEDIN = 'https://www.linkedin.com/in/dr-giorgi-khorbaladze-academician-b1b744103'
AUTHOR_PHOTO = Path(__file__).resolve().parent / 'assets' / 'author.jpg'


@st.cache_data
def _author_photo_b64():
    import base64
    return base64.b64encode(AUTHOR_PHOTO.read_bytes()).decode('ascii') if AUTHOR_PHOTO.exists() else ''


def author_block(lang):
    photo = _author_photo_b64()
    img = (f'<img src="data:image/jpeg;base64,{photo}" alt="" style="width:56px;height:56px;border-radius:50%;'
           f'border:2px solid {ui.C["accent"]};object-fit:cover">') if photo else ''
    st.sidebar.markdown(
        f'<div style="display:flex;align-items:center;gap:.7rem;margin-top:1rem;padding:.7rem;border:1px solid {ui.C["border"]};'
        f'border-radius:12px;background:{ui.C["panel2"]}">{img}<div><div class="wc-label">{ui.esc(tr("author_label", lang))}</div>'
        f'<div style="font-weight:600">{ui.esc(tr("author_name", lang))}</div>'
        f'<a href="{AUTHOR_LINKEDIN}" target="_blank" rel="noopener noreferrer" style="color:{ui.C["accent2"]};font-size:.85rem">LinkedIn ↗</a>'
        f'</div></div>', unsafe_allow_html=True)


def local(value, fmt='%d.%m.%Y %H:%M'):
    return pd.Timestamp(value).tz_convert(TZ).strftime(fmt)



def pct(x):
    return f'{x * 100:.1f}%'


def combined_history(durable, live):
    """Durable collector rows plus live rows (same source, same validation), one per label."""
    rows = {r.period_label_utc: dict(time=r.period_label_utc, value_mw=r.value_mw, quality=r.quality,
                                     retrieved=r.retrieved_at_utc, origin='collector') for r in durable}
    for item in live:
        rows.setdefault(item['time'], dict(item, origin='live'))
    return [rows[k] for k in sorted(rows)]


def latest_due(now):
    t = pd.Timestamp(now - timedelta(seconds=75)).floor('min')
    return t - pd.Timedelta(minutes=t.minute % 3)


def main():
    choice = st.sidebar.radio('ენა / Language', ['ქართული', 'English'])
    lang = 'ka' if choice == 'ქართული' else 'en'
    page = st.sidebar.radio(tr('nav', lang), PAGES, format_func=lambda p: tr(f'page_{p}', lang))
    st.sidebar.caption(tr('tz_note', lang))
    st.sidebar.caption(tr('independent', lang))
    author_block(lang)
    ui.inject()

    @st.fragment(run_every=180)
    def dashboard():
        now = source.utcnow()
        reader = history_reader()
        cache = source_cache()
        cache.adopt_stored(*reader.weather(now))  # second path when Open-Meteo limits this host
        data = cache.snapshot(now, include_archive=page == 'analytics')
        shown = {'forecast': data['forecast'], 'era5': data['archive']}
        for name, error in data['errors'].items():
            if name == 'gse' or not shown.get(name):  # a stored copy with its timestamp is shown instead
                st.warning(tr('source_warning', lang, name=name, code=error))
        {'overview': overview, 'balance': balance_page, 'analytics': analytics, 'forecast': forecast,
         'accuracy': accuracy, 'data': data_page}[page](lang, data, reader, now)
        st.caption(f"{tr('last_check', lang)}: {local(now)} · {tr('auto_refresh', lang)}")

    dashboard()


# ---------------------------------------------------------------------------------------- overview

def overview(lang, data, reader, now):
    rows = combined_history(reader.records(now - timedelta(hours=52), now, now), data['history'])
    df = an.frame(rows)
    latest = rows[-1] if rows else None
    state = generation_state(latest, now)
    ui.hero(tr('app_title', lang), tr('tagline', lang), ui.badge(tr(STATE_KEY[state], lang), state))
    if latest is None:
        st.info(tr('no_data', lang))
        site_map(lang, data, now)
        return
    due = latest_due(now)
    cmp = an.compare_today_yesterday(df, pd.Timestamp(now), due)
    t, y = cmp.today, cmp.yesterday
    y_sub = tr('full_day' if y.complete else 'incomplete_day', lang, pct=pct(y.completeness))
    ui.cards([
        ui.card(tr('now_mw', lang), ui.fmt(latest['value_mw'], 2), 'MW',
                tr('now_sub', lang, time=local(latest['time'], '%H:%M')) + f" · {tr('quality', lang)}: {latest['quality']}", accent=True),
        ui.card(tr('today_energy', lang), ui.fmt(t.energy_mwh, 0), 'MWh',
                tr('so_far', lang, time=local(due, '%H:%M'), pct=pct(t.completeness))),
        ui.card(tr('yesterday_energy', lang), ui.fmt(y.energy_mwh, 0), 'MWh', y_sub),
        ui.card(tr('peak_today', lang), ui.fmt(t.peak_mw, 1), 'MW',
                tr('at_time', lang, time=local(t.peak_time, '%H:%M'), q=df.loc[t.peak_time, 'quality']) if t.peak_time is not None else ''),
    ])
    ui.note(f"{tr('official', lang)} · {tr('cmp_note', lang)}", ui.tag('GSE', 'off'))

    st.subheader(tr('cmp_title', lang))
    left, right = st.columns([1, 2])
    with left:
        delta = cmp.delta_same_time_mwh
        sign = '' if delta is None else ('+' if delta >= 0 else '−')
        ui.cards([
            ui.card(tr('cmp_same_time', lang), ui.fmt(cmp.yesterday_same_time.energy_mwh, 0), 'MWh',
                    tr('so_far', lang, time=local(due - pd.Timedelta(days=1), '%d.%m %H:%M'), pct=pct(cmp.yesterday_same_time.completeness))),
            ui.card(tr('cmp_delta', lang), sign + ui.fmt(abs(delta), 0) if delta is not None else '-', 'MWh',
                    (sign + f'{abs(cmp.delta_same_time_pct):.1f}%') if cmp.delta_same_time_pct is not None else '',
                    sub_class='wc-up' if (delta or 0) >= 0 else 'wc-down'),
        ])
        if t.non_act or y.non_act:
            ui.note(tr('non_act_note', lang, n=t.non_act + y.non_act))
    with right:
        fig = go.Figure()
        for day, name, color, dash in ((y.day, tr('yesterday', lang), ui.C['accent2'], 'dot'), (t.day, tr('today', lang), ui.C['accent'], None)):
            prof = an.hourly_profile(df, day)
            fig.add_scatter(x=prof['hour'], y=prof['mean_mw'], mode='lines+markers', name=name,
                            line=dict(color=color, width=2.5, dash=dash), marker=dict(size=5),
                            customdata=prof['periods'], hovertemplate='%{y:.1f} MW · %{customdata}/20<extra></extra>')
        ui.chart(ui.style(fig, 300, 'MW', tr('hours', lang)).update_xaxes(dtick=3, range=[-0.5, 23.5]))
        ui.note(tr('cmp_chart', lang))

    st.subheader(tr('last24', lang))
    generation_chart(lang, rows, pd.Timestamp(now) - pd.Timedelta(hours=24), pd.Timestamp(now), height=280)

    st.subheader(tr('bal_last24', lang))
    brows = reader.balance(now - timedelta(hours=24), now, now)
    if brows:
        balance_chart(lang, brows, height=320)
        ui.note(tr('bal_intro', lang), ui.tag('GSE', 'off'))
    else:
        st.info(tr('bal_none', lang))

    st.subheader(tr('sites', lang))
    site_map(lang, data, now)


def generation_chart(lang, rows, start, end, height=340):
    """3-minute grid between the first and last stored periods: gaps stay empty, never interpolated."""
    rows = [r for r in rows if start <= pd.Timestamp(r['time']) <= end]
    if not rows:
        st.info(tr('no_data', lang))
        return
    first, last = pd.Timestamp(rows[0]['time']), pd.Timestamp(rows[-1]['time'])
    grid = pd.date_range(first, last, freq='3min')
    by_time = {pd.Timestamp(r['time']): r for r in rows}
    values = [by_time[t]['value_mw'] if t in by_time else None for t in grid]
    fig = go.Figure(go.Scatter(x=[wall(t) for t in grid], y=values, mode='lines', connectgaps=False, name='MW',
                               line=dict(color=ui.C['accent'], width=2), fill='tozeroy', fillcolor='rgba(45,212,191,0.08)'))
    odd = [r for r in rows if r['quality'] != 'ACT']
    if odd:
        fig.add_scatter(x=[wall(r['time']) for r in odd], y=[r['value_mw'] for r in odd], mode='markers',
                        name=f"{tr('quality', lang)} ≠ ACT", marker=dict(color=ui.C['warn'], size=4))
    ui.chart(ui.style(fig, height, 'MW').update_xaxes(type='date', tickformat='%H:%M\n%d.%m'))
    missing = sum(v is None for v in values)
    if missing:
        ui.note(tr('s_missing', lang, n=missing))


def site_wind(packet, index, height, now):
    if not packet:
        return None
    hour = now.replace(minute=0, second=0, microsecond=0)
    return next((v for v in packet['series'][index].by_height[height] if v.valid_at == hour), None)


def site_map(lang, data, now):
    packet = data['forecast']
    records = []
    for i, site in enumerate(SITES):
        current = site_wind(packet, i, 80, now)
        wind = (f"{current.speed_ms:.1f} {tr('ms', lang)}, {compass.label(current.direction_deg, lang)}"
                if current and current.speed_ms is not None else '-')
        records.append(dict(num=str(i + 1), lat=site.latitude, lon=site.longitude, name=site.name_ka if lang == 'ka' else site.name_en,
                            status=site.status_ka if lang == 'ka' else site.status_en, wind=wind,
                            speed=current.speed_ms if current and current.speed_ms is not None else 0.0))
    frame = pd.DataFrame(records)
    layers = [
        pdk.Layer('ScatterplotLayer', data=frame, get_position='[lon, lat]', get_radius=2600, radius_min_pixels=10,
                  get_fill_color=[45, 212, 191, 70], stroked=False, pickable=False),
        pdk.Layer('ScatterplotLayer', data=frame, get_position='[lon, lat]', get_radius=1200, radius_min_pixels=6,
                  get_fill_color=[45, 212, 191, 235], get_line_color=[7, 17, 28], line_width_min_pixels=2, stroked=True, pickable=True),
        # Numbers, not names: pydeck turns string props such as character_set into accessors, so
        # non-ASCII (Georgian) glyphs cannot be requested; ASCII digits render with the default set.
        pdk.Layer('TextLayer', data=frame, get_position='[lon, lat]', get_text='num', get_size=16,
                  get_color=[232, 241, 248], get_pixel_offset=[0, -22]),
    ]
    left, right = st.columns([3, 2])
    with left:
        st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=41.99, longitude=44.17, zoom=8.2),
                                 tooltip={'text': '{name}\n{status}\n80 m: {wind}'}, map_provider='carto', map_style=BASEMAP), height=360)
    with right:
        ui.cards([ui.card(f"{r['num']}. {r['name']}", r['wind'].split(',')[0] if r['wind'] != '-' else '-', '',
                          f"80 m · {r['wind'].split(', ', 1)[1] if ', ' in r['wind'] else ''} · {r['status']}") for r in records])
    ui.note(tr('site_note', lang, model=FORECAST.label), ui.tag(tr('model_wind', lang), 'mdl'))


# ----------------------------------------------------------------------------------------- balance

# Distinct hues with high contrast on the dark theme; wind is a saturated green so it never blends
# into hydro blue. Stack order puts wind at the bottom so its profile is read against zero.
SRC_COLORS = {'wind': '#22c55e', 'solar': '#facc15', 'hydro': '#3b82f6', 'thermal': '#f97316',
              'import': '#a78bfa', 'export': '#f472b6'}
STACK_ORDER = ('wind', 'solar', 'hydro', 'thermal')


def _fill(hex_color, alpha=0.82):
    h = hex_color.lstrip('#')
    return f'rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})'


def balance_frame(rows):
    df = pd.DataFrame([dict(time=r.period_label_utc, hydro=r.hydro_mw, thermal=r.thermal_mw, wind=r.wind_mw, solar=r.solar_mw,
                            generation=r.generation_mw, consumption=r.consumption_mw,
                            imports=r.import_mw if r.import_mw is not None else np.nan,
                            exports=r.export_mw if r.export_mw is not None else np.nan) for r in rows])
    df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.set_index('time').sort_index()
    df['net'] = df['consumption'] - df['generation']
    # Gross flows where parsed (as on GSE's website); older rows fall back to the derived net value.
    df['gross'] = df['imports'].notna()
    df['imp'] = df['imports'].where(df['gross'], df['net'].clip(lower=0))
    df['exp'] = df['exports'].where(df['gross'], (-df['net']).clip(lower=0))
    return df


def balance_chart(lang, rows, height=360):
    df = balance_frame(rows)
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq='3min'))  # gaps stay empty
    x = [wall(t) for t in df.index]
    fig = go.Figure()
    for src in STACK_ORDER:
        fig.add_scatter(x=x, y=df[src], name=tr(f'src_{src}', lang), mode='lines', stackgroup='gen',
                        line=dict(width=1, color=SRC_COLORS[src]), fillcolor=_fill(SRC_COLORS[src]),
                        hovertemplate='%{y:.0f} MW')
    gross = bool(df['gross'].dropna().iloc[-1]) if df['gross'].notna().any() else False  # label follows the latest data
    fig.add_scatter(x=x, y=df['imp'], name=tr('src_import' if gross else 'src_import_net', lang), mode='lines', stackgroup='gen',
                    line=dict(width=1, color=SRC_COLORS['import']), fillcolor=_fill(SRC_COLORS['import'], 0.7),
                    hovertemplate='%{y:.0f} MW')
    if (df['exp'] > 0).any():
        fig.add_scatter(x=x, y=-df['exp'], name=tr('src_export' if gross else 'src_export_net', lang), mode='lines', stackgroup='exp',
                        line=dict(width=1, color=SRC_COLORS['export']), fillcolor=_fill(SRC_COLORS['export'], 0.7),
                        customdata=df['exp'], hovertemplate='%{customdata:.0f} MW')
    fig.add_scatter(x=x, y=df['consumption'], name=tr('consumption', lang), mode='lines',
                    line=dict(color='#ffffff', width=2.2), hovertemplate='%{y:.0f} MW')
    ui.chart(ui.style(fig, height, 'MW').update_xaxes(type='date', tickformat='%H:%M\n%d.%m'))


def renewable_section(lang, df):
    """Factual wind/solar shares from stored GSE balance data; no model involved."""
    st.subheader(tr('ren_title', lang))
    shares = an.renewable_shares(df)
    if shares is None:
        st.info(tr('bal_none', lang))
        return
    ui.cards([
        ui.card(tr('ren_wind', lang), pct(shares['wind']), '', f"{tr('ren_sub', lang)} · {ui.fmt(shares['wind_mwh'], 0)} MWh", accent=True),
        ui.card(tr('ren_ws', lang), pct(shares['wind_solar']), '', tr('ren_sub', lang)),
        ui.card(tr('ren_all', lang), pct(shares['renewable']), '', tr('ren_sub', lang)),
    ])
    c1, c2 = st.columns([3, 2])
    with c1:
        byh = an.wind_share_by_hour(df)
        fig = go.Figure(go.Bar(x=byh['hour'], y=byh['wind_share'] * 100, marker_color=SRC_COLORS['wind'],
                               customdata=byh['periods'], hovertemplate='%{y:.1f}% · n=%{customdata}<extra></extra>'))
        ui.chart(ui.style(fig, 280, '%', tr('hours', lang)).update_xaxes(dtick=3, range=[-0.5, 23.5]).update_layout(hovermode='closest'))
        ui.note(tr('ren_hour', lang))
    with c2:
        st.markdown(f"**{tr('ren_cmp', lang)}**")
        cmp = an.windy_vs_calm(df)
        if cmp is None:
            ui.note(tr('ren_wait', lang))
        else:
            ui.cards([
                ui.card(tr('ren_windy', lang), ui.fmt(cmp['windy_import'], 0), 'MW',
                        tr('ren_cmp_sub', lang, q=tr('ren_top', lang), w=ui.fmt(cmp['windy_wind'], 0),
                           t=ui.fmt(cmp['windy_thermal'], 0), n=cmp['windy_n'])),
                ui.card(tr('ren_calm', lang), ui.fmt(cmp['calm_import'], 0), 'MW',
                        tr('ren_cmp_sub', lang, q=tr('ren_bottom', lang), w=ui.fmt(cmp['calm_wind'], 0),
                           t=ui.fmt(cmp['calm_thermal'], 0), n=cmp['calm_n'])),
            ])
            ui.note(tr('ren_caveat', lang))


def balance_page(lang, data, reader, now):
    ui.hero(tr('page_balance', lang), tr('bal_title', lang))
    nowt = pd.Timestamp(now)
    span = st.radio(tr('range', lang), ['24h', '48h', '7d', '30d'], horizontal=True)
    start = nowt - {'24h': pd.Timedelta(hours=24), '48h': pd.Timedelta(hours=48), '7d': pd.Timedelta(days=7), '30d': pd.Timedelta(days=30)}[span]
    rows = reader.balance(start.to_pydatetime(), now, now)
    if not rows:
        st.info(tr('bal_none', lang))
        return
    df = balance_frame(rows)
    last = df.iloc[-1]
    net = last['net']
    cards = [
        ui.card(tr('bal_now', lang), ui.fmt(last['consumption'], 0), 'MW', local(df.index[-1], '%d.%m %H:%M'), accent=True),
        ui.card(tr('bal_gen_now', lang), ui.fmt(last['generation'], 0), 'MW',
                ' · '.join(f"{tr(f'src_{k}', lang)} {last[k]:.0f}" for k in STACK_ORDER)),
    ]
    if last['gross']:
        cards += [ui.card(tr('bal_imp_now', lang), ui.fmt(last['imp'], 2), 'MW'),
                  ui.card(tr('bal_exp_now', lang), ui.fmt(last['exp'], 2), 'MW')]
    else:
        cards.append(ui.card(tr('bal_net_now', lang), ui.fmt(abs(net), 0), 'MW', tr('bal_net_sub_imp' if net >= 0 else 'bal_net_sub_exp', lang)))
    ui.cards(cards)
    balance_chart(lang, rows)
    ui.note(tr('bal_intro', lang), ui.tag('GSE', 'off'))
    ui.note(tr('bal_flows_note', lang))
    if not df['gross'].all():
        ui.note(tr('bal_net_old', lang))

    energy = df[['hydro', 'thermal', 'wind', 'solar', 'generation', 'consumption']].sum() * an.PERIOD_HOURS
    st.subheader(tr('bal_mix', lang))
    c1, c2 = st.columns([1, 1])
    with c1:
        srcs = list(STACK_ORDER)
        fig = go.Figure(go.Pie(labels=[tr(f'src_{k}', lang) for k in srcs], values=[max(energy[k], 0) for k in srcs], hole=0.55,
                               marker=dict(colors=[SRC_COLORS[k] for k in srcs], line=dict(color=ui.C['bg'], width=2)),
                               sort=False, textinfo='percent', textfont=dict(color='#0b1220', size=13)))
        ui.chart(ui.style(fig, 300).update_layout(hovermode='closest'))
        ui.note(tr('bal_mix_sub', lang))
    with c2:
        imp = max(float(df['imp'].sum()) * an.PERIOD_HOURS, 0.0)
        exp = max(float(df['exp'].sum()) * an.PERIOD_HOURS, 0.0)
        expected = len(an.grid(max(start, df.index.min()), df.index.max()))
        cov = f"{tr('s_complete', lang)}: {pct(len(df) / expected) if expected else '-'} · {len(df)}/{expected}"
        ui.cards([
            ui.card(tr('consumption', lang), ui.fmt(energy['consumption'], 0), 'MWh', cov),
            ui.card(tr('generation', lang), ui.fmt(energy['generation'], 0), 'MWh', cov),
            ui.card(tr('src_import', lang), ui.fmt(imp, 0), 'MWh', f"{tr('src_export', lang)}: {ui.fmt(exp, 0)} MWh"),
        ])
    renewable_section(lang, df)

    st.subheader(tr('bal_profiles', lang))
    hours = (df.index.tz_convert(TZ) - pd.Timedelta(minutes=3)).hour
    prof = df.groupby(hours)[['hydro', 'thermal', 'wind', 'solar', 'consumption', 'imp', 'exp']].mean()
    fig = go.Figure()
    for src in STACK_ORDER:
        fig.add_scatter(x=prof.index, y=prof[src], name=tr(f'src_{src}', lang), mode='lines+markers', line=dict(color=SRC_COLORS[src], width=2.4))
    fig.add_scatter(x=prof.index, y=prof['imp'], name=tr('src_import', lang), mode='lines', line=dict(color=SRC_COLORS['import'], width=1.8, dash='dot'))
    fig.add_scatter(x=prof.index, y=prof['exp'], name=tr('src_export', lang), mode='lines', line=dict(color=SRC_COLORS['export'], width=1.8, dash='dot'))
    fig.add_scatter(x=prof.index, y=prof['consumption'], name=tr('consumption', lang), mode='lines', line=dict(color='#ffffff', width=2.2))
    ui.chart(ui.style(fig, 340, 'MW', tr('hours', lang)).update_xaxes(dtick=3, range=[-0.5, 23.5]))
    ui.note(tr('bal_profiles_note', lang))
    ui.note(tr('bal_quality', lang))
    out = df.reset_index().rename(columns={'index': 'period_label_utc', 'time': 'period_label_utc'})
    st.download_button(tr('download', lang), out.to_csv(index=False), 'windcast_gse_balance.csv', 'text/csv')


# --------------------------------------------------------------------------------------- analytics

def analytics(lang, data, reader, now):
    ui.hero(tr('page_analytics', lang), tr('facts_only', lang))
    nowt = pd.Timestamp(now)
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        span = st.radio(tr('range', lang), ['24h', '7d', '30d', '90d', 'custom'], horizontal=True,
                        format_func=lambda k: tr('custom', lang) if k == 'custom' else k)
    if span == 'custom':
        with c2:
            today = nowt.tz_convert(TZ).date()
            picked = st.date_input(tr('dates', lang), (today - timedelta(days=6), today), max_value=today)
        d0, d1 = (picked if isinstance(picked, tuple) and len(picked) == 2 else (picked, picked)) if picked else (today, today)
        start, end = an.day_bounds(d0)[0], min(an.day_bounds(d1)[1], nowt)
    else:
        start, end = nowt - {'24h': pd.Timedelta(hours=24), '7d': pd.Timedelta(days=7), '30d': pd.Timedelta(days=30),
                             '90d': pd.Timedelta(days=90)}[span], nowt
        with c2:
            hours = st.slider(tr('hours', lang), 0, 23, (0, 23))
    if span == 'custom':
        hours = st.slider(tr('hours', lang), 0, 23, (0, 23))
    with c3:
        complete_only = st.checkbox(tr('complete_only', lang))
    load_from = an.day_bounds(an.local_day(start.ceil('3min')))[0]  # whole days for daily completeness
    rows = combined_history(reader.records(load_from.to_pydatetime(), end.to_pydatetime(), now), data['history'])
    df = an.frame(rows)
    codes = sorted(df['quality'].unique()) if len(df) else []
    qualities = st.multiselect(tr('quality_filter', lang), codes, default=codes) if codes else []
    f = an.Filters(start, end, hours[0], hours[1], tuple(qualities) if codes else None, complete_only)
    part, grid, present = an.apply_filters(df, f, nowt)
    s = an.summary(part, grid, present)
    ui.cards([
        ui.card(tr('s_total', lang), ui.fmt(s['total_mwh'], 0), 'MWh', tr('s_missing', lang, n=s['missing']), accent=True),
        ui.card(tr('s_mean', lang), ui.fmt(s['mean']), 'MW', f"{tr('s_median', lang)}: {ui.fmt(s['median'])} MW"),
        ui.card(tr('s_minmax', lang), f"{ui.fmt(s['min'])} / {ui.fmt(s['max'])}", 'MW', f"{tr('s_std', lang)}: {ui.fmt(s['std'])} MW"),
        ui.card(tr('s_complete', lang), pct(s['completeness']), '', f"{s['stored']} / {s['expected']}"),
    ])
    if not len(part):
        st.info(tr('no_data', lang))
    else:
        st.subheader(tr('series_title', lang))
        if end - start <= pd.Timedelta(days=7):
            sel = [dict(time=t, value_mw=v, quality=q) for t, v, q in zip(part.index, part['value_mw'], part['quality'], strict=True)]
            generation_chart(lang, sel, start, end)
        else:
            hourly = part['value_mw'].groupby((part.index - pd.Timedelta(minutes=3)).floor('h')).mean()
            hourly = hourly.reindex(pd.date_range(hourly.index.min(), hourly.index.max(), freq='h'))
            fig = go.Figure(go.Scatter(x=[wall(t) for t in hourly.index], y=hourly.values, mode='lines', connectgaps=False,
                                       line=dict(color=ui.C['accent'], width=1.6), name='MW'))
            ui.chart(ui.style(fig, 320, 'MW').update_xaxes(type='date', tickformat='%H:%M\n%d.%m'))
            ui.note(tr('hourly_mean_note', lang))
        days = an.daily(df, start, end, nowt, latest_due(now))
        if complete_only:
            days = days[days['complete']]
        days = days[days['stored'] > 0]
        if len(days):
            st.subheader(tr('daily_title', lang))
            colors = [ui.C['accent'] if c else ui.C['warn'] for c in days['complete']]
            fig = go.Figure(go.Bar(x=[str(d) for d in days['day']], y=days['energy_mwh'], marker_color=colors, name='MWh',
                                   customdata=np.stack([days['completeness'] * 100], axis=-1),
                                   hovertemplate='%{y:.0f} MWh · %{customdata[0]:.1f}%<extra></extra>'))
            if len(days) >= 7:
                roll = days.set_index('day')['energy_mwh'].where(days.set_index('day')['complete']).rolling(7, min_periods=4).mean()
                fig.add_scatter(x=[str(d) for d in roll.index], y=roll.values, mode='lines', name=tr('rolling', lang),
                                line=dict(color=ui.C['accent2'], width=2))
            ui.chart(ui.style(fig, 300, 'MWh').update_xaxes(type='category'))
            ui.note(f"■ {tr('complete', lang)} · ■ {tr('incomplete', lang)}")
            agg_choice = st.radio(tr('aggregation', lang), ['day', 'week', 'month'], horizontal=True,
                                  format_func=lambda k: tr(f'agg_{k}', lang))
            if agg_choice == 'day':
                table = days[['day', 'energy_mwh', 'mean_mw', 'min_mw', 'max_mw', 'completeness']].copy()
            else:
                table = an.aggregate(days, 'W' if agg_choice == 'week' else 'M').drop(columns=['complete_days'])
            table['completeness'] = (table['completeness'] * 100).round(1)
            labels = {'day': tr('dates', lang), 'period': tr('range', lang), 'energy_mwh': f"{tr('s_total', lang)}, MWh",
                      'mean_mw': f"{tr('s_mean', lang)}, MW", 'min_mw': 'Min, MW', 'max_mw': 'Max, MW',
                      'days': tr('dates', lang), 'completeness': f"{tr('s_complete', lang)}, %"}
            st.dataframe(table.round(1).rename(columns=labels), width='stretch', hide_index=True)
            pattern = an.weekday_pattern(days)
            c1, c2 = st.columns(2)
            with c1:
                st.subheader(tr('weekday_title', lang))
                if pattern is None:
                    ui.note(tr('weekday_wait', lang))
                else:
                    names = tr('weekdays', lang).split(',')
                    fig = go.Figure(go.Bar(x=[names[w] for w in pattern['weekday']], y=pattern['mean'], marker_color=ui.C['accent2']))
                    ui.chart(ui.style(fig, 260, 'MWh'))
            with c2:
                st.subheader(tr('dist_title', lang))
                fig = go.Figure(go.Histogram(x=part['value_mw'], nbinsx=40, marker_color=ui.C['accent']))
                ui.chart(ui.style(fig, 260, '', 'MW').update_layout(hovermode='closest'))
        out = part.reset_index().rename(columns={'time': 'period_label_utc'})
        st.download_button(tr('download', lang), out.to_csv(index=False), 'windcast_gse_filtered.csv', 'text/csv')

    st.subheader(tr('era5_title', lang))
    ui.note(f"{REANALYSIS.label} · {tr('era5_note', lang)}", ui.tag(tr('model_wind', lang), 'mdl'))
    archive = data['archive']
    if archive:
        c1, c2 = st.columns(2)
        idx = c1.selectbox(tr('site', lang), range(len(SITES)), format_func=lambda i: SITES[i].name_ka if lang == 'ka' else SITES[i].name_en, key='era5_site')
        height = c2.selectbox(tr('height', lang), REANALYSIS.heights, key='era5_h', format_func=lambda h: f'{h} m')
        show_series(archive['series'][idx].by_height[height], lang, None)
    else:
        st.info(tr('st_unavailable', lang))


# ---------------------------------------------------------------------------------------- forecast

def forecast(lang, data, reader, now):
    ui.hero(tr('page_forecast', lang), tr('wx_note', lang))
    mw_forecast(lang, data, reader, now)
    st.subheader(tr('wx_title', lang))
    c1, c2 = st.columns(2)
    idx = c1.selectbox(tr('site', lang), range(len(SITES)), format_func=lambda i: SITES[i].name_ka if lang == 'ka' else SITES[i].name_en)
    height = c2.selectbox(tr('height', lang), FORECAST.heights, index=1, format_func=lambda h: f'{h} m')
    packet = data['forecast']
    state, hours = weather_state(packet, now, idx, height)
    st.markdown(ui.badge(f"{tr(STATE_KEY[state], lang)} · {FORECAST.label}", state), unsafe_allow_html=True)
    if not packet:
        st.info(tr('wx_unavailable', lang))
        return
    values = [v for v in packet['series'][idx].by_height[height]
              if now.replace(minute=0, second=0, microsecond=0) <= v.valid_at <= now + timedelta(hours=72)]
    via = f" ({tr('collector_copy', lang)})" if packet.get('origin') == 'collector' else ''
    ui.note(f"{tr('run', lang)}: {local(packet['run'])} · {tr('retrieved', lang)}: {local(packet['retrieved'])}{via}", ui.tag(tr('model_wind', lang), 'mdl'))
    if values:
        ui.note(tr('valid', lang, a=local(values[0].valid_at), b=local(values[-1].valid_at), h=hours))
    show_series(values, lang, now, height)


@st.cache_data(ttl=3600, show_spinner=False)
def _model_inputs(gse_key, hist_key, live_key, _df, _train, _live, now_hour):
    return mwmodel.run(mwmodel.hourly_target(_df), _train, _live, now_hour)


def mw_forecast(lang, data, reader, now):
    st.subheader(tr('mw_title', lang))
    ui.note(tr('mw_disclaimer', lang), ui.tag(tr('estimate', lang), 'est'))
    nowt = pd.Timestamp(now)
    rows = combined_history(reader.records(now - timedelta(days=31), now, now), data['history'])
    df = an.frame(rows)
    hist = reader.hist_forecast(now)
    archive = reader.forecast_archive(now)
    if hist is not None:
        train = mwmodel.weather_table(hist['series'], len(SITES))
        hist_key = hist['sha256']
    else:
        train = mwmodel.reference_table(ver.analysis_reference(archive), len(SITES))
        hist_key = f'archive-{len(archive)}'
    live = mwmodel.weather_table(data['forecast']['series'], len(SITES)) if data['forecast'] else None
    live_key = data['forecast']['sha256'] if data['forecast'] else None
    res = _model_inputs(len(df), hist_key, live_key, df, train, live, nowt.floor('h'))
    if res.status != 'ok':
        st.info(tr('mw_insufficient', lang, need=mwmodel.MIN_PAIRED_HOURS, have=res.paired_hours))
        return
    target = mwmodel.hourly_target(df)
    recent = target[target.index >= nowt - pd.Timedelta(hours=48)]
    fig = go.Figure()
    fig.add_scatter(x=[wall(t) for t in recent.index], y=recent.values, mode='lines', name=tr('mw_actual', lang),
                    line=dict(color=ui.C['accent'], width=2))
    if res.forecast is not None and len(res.forecast):
        fc = res.forecast
        x = [wall(t) for t in fc.index]
        fig.add_scatter(x=x + x[::-1], y=list(fc['high']) + list(fc['low'][::-1]), fill='toself', mode='lines',
                        line=dict(width=0), fillcolor='rgba(167,139,250,0.18)', name=tr('mw_band', lang), hoverinfo='skip')
        fig.add_scatter(x=x, y=fc['mw'], mode='lines', name=tr('mw_estimate', lang), line=dict(color=ui.C['model'], width=2.5, dash='dash'))
    now_marker(fig, nowt, lang)
    skill_note(lang, res)
    ui.style(fig, 340, 'MW')
    xs = [t for tr_ in fig.data for t in (tr_.x or ())]
    if xs:
        vals, text = time_ticks(pd.Timestamp(min(xs)).tz_localize(TZ), pd.Timestamp(max(xs)).tz_localize(TZ))
        fig.update_xaxes(type='date', tickvals=vals, ticktext=text, hoverformat='%d.%m %H:%M')
    ui.chart(fig)
    notes = [tr('mw_band_note', lang)]
    if data['forecast']:
        notes.insert(0, tr('mw_vintage', lang, run=local(data['forecast']['run'])))
    ui.note(' · '.join(notes))
    st.markdown(f"**{tr('mw_eval', lang, n=res.test_hours, start=local(res.test_start))}**")
    table = [dict(m=tr('model', lang), **res.model), dict(m=tr('climatology', lang), **res.climatology)]
    table += [dict(m=tr('persistence', lang, h=h), **v) for h, v in res.persistence.items()]
    frame = pd.DataFrame(table).rename(columns={'m': tr('metric', lang), 'mae': 'MAE, MW', 'rmse': 'RMSE, MW', 'bias': 'Bias, MW', 'n': 'n'})
    st.dataframe(frame.round(1), width='stretch', hide_index=True)
    with st.expander(tr('mw_method', lang)):
        st.write(tr('mw_method_text', lang))


def skill_note(lang, res):
    """State plainly whether the held-out model error beats the fair day-ahead baseline."""
    base = mwmodel.fair_baseline(res)
    if base is None or not res.model:
        return
    key, best = base
    name = tr('climatology', lang) if key == 'climatology' else tr('persistence', lang, h=24)
    kw = dict(m=ui.fmt(res.model['mae']), b=name, bm=ui.fmt(best), n=res.test_hours)
    if res.model['mae'] >= best:
        st.warning(tr('mw_weak', lang, **kw))
    else:
        st.info(tr('mw_skill', lang, **kw))


def show_series(values, lang, now, height_m=None):
    if not values:
        st.info(tr('no_data', lang))
        return
    frame = series_frame(values)
    fig = series_figure(frame, lang, height_m)
    if now is not None and frame.index.min() <= now <= frame.index.max():
        now_marker(fig, now, lang, rows=True)
    ui.chart(fig)
    ui.note(tr('wx_dir_note', lang))
    display = pd.DataFrame({tr('speed', lang): frame.speed.round(2), tr('direction', lang): frame.direction,
                            tr('direction_text', lang): [compass.sector(d, lang) or '-' for d in frame.direction]})
    display.index = [local(t) for t in frame.index]
    with st.expander(tr('table', lang)):
        st.dataframe(display, width='stretch')


# ---------------------------------------------------------------------------------------- accuracy

def accuracy(lang, data, reader, now):
    ui.hero(tr('page_accuracy', lang), tr('acc_intro', lang))
    archive = reader.forecast_archive(now)
    ui.note(tr('runs_archived', lang, n=len(archive)), ui.tag(tr('model_wind', lang), 'mdl'))
    ref_kind = st.radio(tr('reference', lang), ['analysis', 'era5'], horizontal=True, format_func=lambda k: tr(f'ref_{k}', lang))
    ref = ver.analysis_reference(archive) if ref_kind == 'analysis' else ver.era5_reference(data['archive'] or reader.weather(now)[1])
    p = ver.pairs(archive, ref)
    if p.empty:
        st.info(tr('acc_none', lang))
        return
    by_lead = ver.scores(p, by=('lead',))
    leads = [b[2] for b in ver.LEAD_BUCKETS if b[2] in set(by_lead['lead'])]
    by_lead = by_lead.set_index('lead').loc[leads].reset_index()
    ui.cards([ui.card(f"{tr('lead', lang)} {r['lead']}", ui.fmt(r['mae'], 2), 'm/s',
                      f"RMSE {ui.fmt(r['rmse'], 2)} · {tr('bias', lang).split(',')[0]} {r['bias']:+.2f} · n={r['n']}") for _, r in by_lead.iterrows()])
    detail = ver.scores(p)
    detail['site'] = [SITES[i].name_ka if lang == 'ka' else SITES[i].name_en for i in detail['site']]
    fig = go.Figure()
    for h, color in zip(sorted(detail['height'].unique()), (ui.C['accent'], ui.C['accent2'], ui.C['model'], ui.C['warn']), strict=False):
        g = ver.scores(p[p['height'] == h], by=('lead',)).set_index('lead').reindex(leads)
        fig.add_scatter(x=leads, y=g['mae'], mode='lines+markers', name=f'{h} m', line=dict(color=color, width=2))
    ui.chart(ui.style(fig, 300, tr('mae', lang), tr('lead', lang)))
    table = detail.rename(columns={'site': tr('site', lang), 'height': tr('height', lang), 'lead': tr('lead', lang), 'n': tr('pairs', lang),
                                   'mae': tr('mae', lang), 'rmse': tr('rmse', lang), 'bias': tr('bias', lang), 'dir_mae': tr('dir_mae', lang)})
    st.dataframe(table.drop(columns=['dir_n']).round(2), width='stretch', hide_index=True)


# -------------------------------------------------------------------------------------------- data

def data_page(lang, data, reader, now):
    ui.hero(tr('page_data', lang), tr('health_title', lang))
    status = reader.status(now)
    age = collector_age(status, now)
    nowt = pd.Timestamp(now)
    latest_label = pd.Timestamp(status['latest_label_utc']) if status and status.get('latest_label_utc') else None
    rows = combined_history(reader.records(now - timedelta(days=7), now, now), data['history'])
    df = an.frame(rows)
    due = latest_due(now)
    cov = {}
    first_stored = df.index.min() if len(df) else None
    for days in (1, 7):
        start = nowt - pd.Timedelta(days=days)
        if first_stored is not None:
            start = max(start, first_stored)  # before the first stored period nothing was collected yet
        part, grid, present = an.apply_filters(df, an.Filters(start, due), nowt)
        cov[days] = (present, len(grid))
    stale = latest_label is None or nowt - latest_label > pd.Timedelta(hours=6)
    if age is None:
        state, text = 'unavailable', tr('h_never', lang)
    elif stale:
        state, text = 'stale', tr('h_stale', lang)
    else:
        state, text = 'fresh', tr('h_healthy', lang)
    st.markdown(ui.badge(text, state), unsafe_allow_html=True)
    ui.cards([
        ui.card(tr('h_last_success', lang), local(now - age) if age is not None else '-', '', '', accent=True),
        ui.card(tr('h_latest_label', lang), local(latest_label) if latest_label is not None else '-'),
        ui.card(tr('h_coverage', lang), pct(cov[1][0] / cov[1][1]) if cov[1][1] else '-', '',
                f"{tr('h_window', lang, d='24h')} · {tr('s_missing', lang, n=cov[1][1] - cov[1][0])}"),
        ui.card(tr('h_coverage', lang), pct(cov[7][0] / cov[7][1]) if cov[7][1] else '-', '',
                f"{tr('h_window', lang, d='7d')} · {tr('s_missing', lang, n=cov[7][1] - cov[7][0])}"),
    ])
    if first_stored is not None and first_stored > nowt - pd.Timedelta(days=7):
        ui.note(tr('h_since', lang, t=local(first_stored)))
    run = (status or {}).get('last_run', {})
    if run:
        ui.note(tr('h_backfill', lang, req=run.get('requested', 0), ins=run.get('inserted', 0), bf=run.get('backfilled', 0),
                   lb=ui.fmt(run.get('lookback_used_hours', status.get('lookback_hours', 12)), 0)))
    deep = (status or {}).get('deep_backfill')
    if deep and deep.get('cursor'):
        ui.note(tr('h_deep', lang, cur=local(deep['cursor']), state=tr('h_deep_done' if deep.get('done') else 'h_deep_running', lang)))

    st.subheader(tr('gaps_title', lang))
    first = max(df.index.min(), nowt - pd.Timedelta(days=7)) if len(df) else None
    holes = an.gaps(df, first, df.index.max()) if first is not None else []
    if holes:
        st.dataframe(pd.DataFrame([{tr('gap_from', lang): local(a), tr('gap_to', lang): local(b), tr('gap_n', lang): n} for a, b, n in holes[-50:]]),
                     width='stretch', hide_index=True)
    else:
        ui.note(tr('no_gaps', lang))

    st.subheader(tr('how_title', lang))
    st.write(tr('how_text', lang))
    st.subheader(tr('method_title', lang))
    st.markdown(tr('method_text', lang, fc=FORECAST.label, ra=REANALYSIS.label))
    st.warning(tr('disclaimer', lang))
    st.caption(tr('hosting', lang))
    st.markdown('[GSE](https://www.gse.com.ge/) · [Open-Meteo (CC BY 4.0)](https://open-meteo.com/) · '
                '[Source methodology](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/tree/main/docs/sources) · '
                '[Data (CSV)](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/tree/data/gse)')


if __name__ == '__main__':
    main()
