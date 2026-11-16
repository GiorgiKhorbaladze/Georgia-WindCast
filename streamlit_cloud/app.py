"""Georgia WindCast - Streamlit Community Cloud edition.

Durable GSE history comes from the scheduled collector (collector.py, GitHub Actions -> `data`
branch); the live cache (data.py) fills the minutes since its last run and serves the Open-Meteo
products. Production parsers and freshness rules from backend/app are reused unchanged.
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data as source  # noqa: E402
from data import FORECAST, REANALYSIS, SITES, SourceCache, generation_state, weather_state  # noqa: E402
from history import DATA_BASE, HistoryReader, collector_age  # noqa: E402

st.set_page_config(page_title='Georgia WindCast', page_icon='🌬️', layout='wide')
TZ = ZoneInfo('Asia/Tbilisi')
BASEMAP = 'https://tiles.openfreemap.org/styles/dark'  # same basemap as the main product
ICON = {'fresh': '🟢', 'unverified': '🟡', 'stale': '🟠', 'unavailable': '⚪'}
COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']


@st.cache_resource
def source_cache():
    return SourceCache()


@st.cache_resource
def history_reader():
    base = os.environ.get('WINDCAST_DATA_BASE_URL', DATA_BASE)
    return HistoryReader(lambda: httpx.Client(timeout=10, follow_redirects=False), base)


def local(value):
    return value.astimezone(TZ).strftime('%d.%m.%Y %H:%M')


def wall(value):
    """Tbilisi wall-clock string for chart axes, independent of the viewer's time zone."""
    return value.astimezone(TZ).strftime('%Y-%m-%dT%H:%M:%S')


def combined_history(durable, live):
    """Durable collector rows plus live rows (same source, same validation), one per label."""
    rows = {r.period_label_utc: dict(time=r.period_label_utc, value_mw=r.value_mw, quality=r.quality,
                                     retrieved=r.retrieved_at_utc, origin='collector') for r in durable}
    for item in live:
        rows.setdefault(item['time'], dict(item, origin='live'))
    return [rows[k] for k in sorted(rows)]


def main():
    language = st.sidebar.radio('ენა / Language', ['ქართული', 'English'])
    ka = language == 'ქართული'

    def tr(ge, en):
        return ge if ka else en

    states = {'fresh': tr('აქტუალური', 'Fresh'), 'stale': tr('მოძველებული / არასრული', 'Stale / partial'),
              'unavailable': tr('მიუწვდომელია', 'Unavailable'),
              'unverified': tr('დაუდასტურებელი (ხარისხი ≠ ACT)', 'Unverified (quality ≠ ACT)')}
    page = st.sidebar.radio(tr('გვერდები', 'Pages'), [tr('მიმოხილვა', 'Overview'), tr('პროგნოზი', 'Forecast'),
                             tr('ისტორია', 'History'), tr('მონაცემების შესახებ', 'About data')])
    st.sidebar.caption(tr('დრო: თბილისი (UTC+4)', 'Time: Tbilisi (UTC+4)'))
    st.sidebar.caption(tr('დამოუკიდებელი საინფორმაციო პროექტი', 'Independent informational project'))
    st.title('Georgia WindCast')
    st.caption(tr('საქართველოს ქარის ჯამური გენერაცია (GSE) და ქარის სადგურების ლოკაციების მოდელური ქარი',
                  "Georgia's national wind generation (GSE) and model wind at wind-farm locations"))

    if page == tr('მონაცემების შესახებ', 'About data'):
        about(tr)
        return

    @st.fragment(run_every=180)
    def dashboard():
        now = source.utcnow()
        data = source_cache().snapshot(now, include_archive=page == tr('ისტორია', 'History'))
        reader = history_reader()
        for name, error in data['errors'].items():
            st.warning(tr(f'{name}: განახლება ვერ შესრულდა ({error}). ნაჩვენებია ბოლო მიღებული მონაცემები მათი დროით.',
                          f'{name}: refresh failed ({error}). Showing the last data received, with its time.'))
        if page == tr('მიმოხილვა', 'Overview'):
            overview(tr, ka, states, data, reader, now)
        elif page == tr('პროგნოზი', 'Forecast'):
            forecast(tr, ka, states, data, now)
        else:
            history(tr, ka, data, reader, now)
        st.caption(tr('ბოლო შემოწმება: ', 'Last check: ') + local(now) + ' · ' +
                   tr('გვერდი ახლდება ყოველ 3 წუთში.', 'The page refreshes every 3 minutes.'))

    dashboard()


def collector_note(tr, reader, now):
    status = reader.status(now)
    age = collector_age(status, now)
    if age is None:
        st.caption(tr('მუდმივი შემგროვებელი ჯერ არ გაშვებულა; ისტორია მხოლოდ ცოცხალი შემოწმებიდანაა.',
                      'The durable collector has not run yet; history comes from live checks only.'))
    else:
        text = tr(f'მუდმივი შემგროვებლის ბოლო წარმატებული გაშვება: {local(now - age)}',
                  f'Durable collector last succeeded: {local(now - age)}')
        (st.warning if age > timedelta(hours=6) else st.caption)(text)
    if reader.error:
        st.caption(tr(f'შენახული ისტორია დროებით მიუწვდომელია ({reader.error}).',
                      f'Stored history temporarily unavailable ({reader.error}).'))


def overview(tr, ka, states, data, reader, now):
    durable = reader.records(now - timedelta(hours=24), now, now)
    rows = combined_history(durable, data['history'])
    latest = rows[-1] if rows else None
    state = generation_state(latest, now)
    st.subheader(tr('ქარის ჯამური გენერაცია (GSE)', 'National wind generation (GSE)'))
    cols = st.columns(3)
    cols[0].metric(tr('3-წუთიანი საშუალო, MW', '3-minute average, MW'), f"{latest['value_mw']:.2f}" if latest else '-')
    cols[1].metric(tr('GSE-ის დროის ნიშნული', 'GSE timestamp'), local(latest['time']) if latest else '-')
    cols[2].metric(tr('ხარისხის კოდი', 'Quality code'), latest['quality'] if latest else '-')
    st.markdown(f"{ICON[state]} **{states[state]}**")
    if latest:
        st.caption(tr('მიღებულია: ', 'Retrieved: ') + local(latest['retrieved']) + ' · ' +
                   tr('აქტუალურობა ითვლება წყაროს დროიდან (≤ 10 წთ).', 'Freshness is measured from the source time (≤ 10 min).'))
    if rows:
        generation_chart(tr, rows, now - timedelta(hours=24), now, height=260)
    st.subheader(tr('ქარის სადგურების ლოკაციები', 'Wind-farm locations'))
    site_map(tr, ka, data, now)


def site_wind(packet, index, height, now):
    if not packet:
        return None
    hour = now.replace(minute=0, second=0, microsecond=0)
    return next((v for v in packet['series'][index].by_height[height] if v.valid_at == hour), None)


def direction_text(deg):
    return f'{deg:.0f}° ({COMPASS[int((deg + 22.5) % 360 // 45)]})' if deg is not None else '-'


def site_map(tr, ka, data, now):
    packet = data['forecast']
    records = []
    for i, site in enumerate(SITES):
        current = site_wind(packet, i, 80, now)
        wind = (f'{current.speed_ms:.1f} m/s, {direction_text(current.direction_deg)}'
                if current and current.speed_ms is not None else '-')
        records.append(dict(num=str(i + 1), lat=site.latitude, lon=site.longitude, name=site.name_ka if ka else site.name_en,
                            status=site.status_ka if ka else site.status_en, wind=wind))
    frame = pd.DataFrame(records)
    layers = [
        pdk.Layer('ScatterplotLayer', data=frame, get_position='[lon, lat]', get_radius=1500,
                  radius_min_pixels=7, get_fill_color=[57, 212, 188, 220], get_line_color=[9, 21, 33],
                  line_width_min_pixels=2, stroked=True, pickable=True),
        # Numbers, not names: pydeck turns string props such as character_set into accessors, so
        # non-ASCII (Georgian) glyphs cannot be requested; ASCII digits render with the default set.
        pdk.Layer('TextLayer', data=frame, get_position='[lon, lat]', get_text='num', get_size=16,
                  get_color=[237, 245, 250], get_pixel_offset=[0, -22]),
    ]
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=41.99, longitude=44.17, zoom=8.3),
                             tooltip={'text': '{name}\n{status}\n80 m: {wind}'}, map_provider='carto',
                             map_style=BASEMAP), height=380)
    for r in records:
        st.markdown(f"**{r['num']}. {r['name']}** · {r['status']} · 80 m: {r['wind']}")
    st.caption(tr('წერტილი წარმოადგენს სადგურის ტერიტორიას და არა ტურბინას. ქარი - მოდელის მნიშვნელობა მიმდინარე საათისთვის '
                  f'({FORECAST.label}), არა გაზომვა. სადგურების გენერაციას GSE არ აქვეყნებს.',
                  'Points represent the wind-farm area, not turbines. Wind is the model value for the current hour '
                  f'({FORECAST.label}), not a measurement. GSE does not publish per-plant output.'))
    st.caption('Basemap: [OpenFreeMap](https://openfreemap.org) © [OpenMapTiles](https://www.openmaptiles.org/) '
               '© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)')


def forecast(tr, ka, states, data, now):
    idx = st.selectbox(tr('ობიექტი', 'Site'), range(len(SITES)), format_func=lambda i: SITES[i].name_ka if ka else SITES[i].name_en)
    height = st.selectbox(tr('სიმაღლე, მ', 'Height, m'), FORECAST.heights, index=1)
    packet = data['forecast']
    state, hours = weather_state(packet, now, idx, height)
    st.markdown(f"{ICON[state]} **{states[state]}** · {FORECAST.label}")
    st.caption(tr('მოდელური ქარი: არ არის გაზომვა და არ არის გენერაციის (MW) პროგნოზი. 200 მ მხარდაჭერილი არ არის.',
                  'Model wind: not a measurement and not a generation (MW) forecast. 200 m is not supported.'))
    if not packet:
        st.info(tr('პროგნოზი ჯერ მიუწვდომელია.', 'Forecast is currently unavailable.'))
        return
    values = [v for v in packet['series'][idx].by_height[height]
              if now.replace(minute=0, second=0, microsecond=0) <= v.valid_at <= now + timedelta(hours=72)]
    st.caption(tr('მოდელის გაშვება: ', 'Model run: ') + local(packet['run']) + ' · ' + tr('მიღებულია: ', 'Retrieved: ') + local(packet['retrieved']))
    if values:
        st.caption(tr(f'მოქმედების დრო: {local(values[0].valid_at)} - {local(values[-1].valid_at)} · უწყვეტი დაფარვა წინ: {hours} სთ (მაქს. 72).',
                      f'Valid time: {local(values[0].valid_at)} - {local(values[-1].valid_at)} · continuous forward coverage: {hours} h (max 72).'))
    show_series(values, tr, 'Forecast', now)


def generation_chart(tr, rows, start, end, height=360):
    """3-minute grid between the first and last stored periods: missing periods are gaps, never
    interpolated. Periods after the last stored one are not drawn; the freshness badge reports a
    source that stopped updating."""
    first = max(start, rows[0]['time'])
    last = min(end, rows[-1]['time'])
    grid = pd.date_range(first, last, freq='3min')
    by_time = {r['time']: r for r in rows}
    values = [by_time[t.to_pydatetime()]['value_mw'] if t.to_pydatetime() in by_time else None for t in grid]
    figure = go.Figure(go.Scatter(x=[wall(t) for t in grid], y=values, mode='lines', connectgaps=False,
                                  name='MW', line=dict(color='#39d4bc')))
    odd = [r for r in rows if r['quality'] != 'ACT' and r['time'] >= first]
    if odd:
        figure.add_scatter(x=[wall(r['time']) for r in odd], y=[r['value_mw'] for r in odd], mode='markers',
                           name=tr('ხარისხი ≠ ACT', 'quality ≠ ACT'), marker=dict(color='#f5b84a', size=6))
    figure.update_layout(yaxis_title='MW', xaxis_title=tr('დრო (თბილისი)', 'Time (Tbilisi)'), xaxis_type='date',
                         height=height, margin=dict(l=10, r=10, t=30, b=10),
                         legend=dict(orientation='h', yanchor='bottom', y=1.0, x=0))
    st.plotly_chart(figure, width='stretch', config={'displayModeBar': False})
    missing = sum(v is None for v in values)
    if missing:
        st.caption(tr(f'ხარვეზი: {missing} პერიოდი (3 წთ) არ არის შენახული - არ გამოქვეყნებულა ან ვერ მოგროვდა.',
                      f'Gaps: {missing} three-minute periods not stored (not published or not collected).'))


def history(tr, ka, data, reader, now):
    st.subheader(tr('გენერაციის ისტორია', 'Generation history'))
    span = st.radio(tr('პერიოდი', 'Range'), ['24h', '7d', '30d'], horizontal=True,
                    format_func=lambda k: {'24h': tr('24 საათი', '24 hours'), '7d': tr('7 დღე', '7 days'),
                                           '30d': tr('30 დღე', '30 days')}[k])
    start = now - {'24h': timedelta(hours=24), '7d': timedelta(days=7), '30d': timedelta(days=30)}[span]
    rows = [r for r in combined_history(reader.records(start, now, now), data['history']) if r['time'] >= start]
    collector_note(tr, reader, now)
    if rows:
        generation_chart(tr, rows, start, now)
        st.caption(tr(f'შენახული პერიოდები: {len(rows)} · ისტორია ამ დიაპაზონში იწყება {local(rows[0]["time"])}-დან.',
                      f'Stored periods: {len(rows)} · history in this range starts at {local(rows[0]["time"])}.'))
        frame = pd.DataFrame(rows)
        st.download_button(tr('CSV ჩამოტვირთვა (UTC)', 'Download CSV (UTC)'), frame.to_csv(index=False),
                           'windcast_gse_history.csv', 'text/csv')
    else:
        st.info(tr('ამ პერიოდისთვის ჩანაწერები არ არის.', 'No readings for this range.'))
    st.subheader(tr('ERA5 რეანალიზი', 'ERA5 reanalysis'))
    st.caption(REANALYSIS.label + ' · ' + tr('7 დღე, 5-დღიანი დაყოვნებით; მოდელის რეანალიზი, არა გაზომვა.',
                                             'Seven days with a five-day lag; model reanalysis, not observations.'))
    archive = data['archive']
    if archive:
        idx = st.selectbox(tr('ობიექტი', 'Site'), range(len(SITES)), format_func=lambda i: SITES[i].name_ka if ka else SITES[i].name_en)
        height = st.selectbox(tr('სიმაღლე, მ', 'Height, m'), REANALYSIS.heights)
        st.caption(tr('მიღებულია: ', 'Retrieved: ') + local(archive['retrieved']))
        show_series(archive['series'][idx].by_height[height], tr, 'ERA5', None)
    else:
        st.info(tr('რეანალიზი მიუწვდომელია.', 'Reanalysis unavailable.'))


def show_series(values, tr, label, now):
    if not values:
        st.info(tr('მონაცემები არ არის.', 'No data.'))
        return
    # Reindex to hourly resolution: omitted timestamps must create visible gaps too.
    frame = pd.DataFrame([dict(time=v.valid_at, speed=v.speed_ms, direction=v.direction_deg) for v in values]).set_index('time')
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq='h'))
    x = [wall(t) for t in frame.index]
    figure = go.Figure(go.Scatter(x=x, y=frame.speed, mode='lines', connectgaps=False, name=tr('სიჩქარე, მ/წმ', 'Speed, m/s'),
                                  line=dict(color='#39d4bc')))
    figure.add_scatter(x=x, y=frame.direction, mode='markers', yaxis='y2', name=tr('მიმართულება (საიდან), °', 'Direction (from), °'),
                       marker=dict(color='#9db4c6', size=4))
    if now is not None:
        figure.add_vline(x=wall(now), line_dash='dot', line_color='#f5b84a')
    figure.update_layout(yaxis=dict(title='m/s', rangemode='tozero'),
                         yaxis2=dict(title='°', overlaying='y', side='right', range=[0, 360], dtick=90, showgrid=False),
                         xaxis_title=tr('დრო (თბილისი)', 'Time (Tbilisi)'), xaxis_type='date', height=380,
                         margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation='h', yanchor='bottom', y=1.0, x=0))
    st.plotly_chart(figure, width='stretch', config={'displayModeBar': False})
    display = frame.copy()
    display.index = [local(t) for t in frame.index]
    display.columns = [tr('სიჩქარე, მ/წმ', 'Speed, m/s'), tr('მიმართულება FROM, °', 'Direction FROM, °')]
    with st.expander(tr('ცხრილი', 'Table')):
        st.dataframe(display, width='stretch')


def about(tr):
    st.subheader(tr('წყაროები, მეთოდოლოგია და შეზღუდვები', 'Sources, methodology and limitations'))
    st.markdown(tr(
        '- **GSE:** ქარის სადგურების ჯამური გენერაცია, 3-წუთიანი საშუალო, MW, სს „საქართველოს სახელმწიფო ელექტროსისტემის“ '
        'საჯარო ფაილებიდან. დროის ნიშნული და ხარისხის კოდი ნაჩვენებია წყაროს მიხედვით. ACT-ისგან განსხვავებული კოდი '
        'მონიშნულია, როგორც დაუდასტურებელი; მნიშვნელობა არ იშლება და არ კორექტირდება. ცალკეული სადგურების გენერაციას GSE არ აქვეყნებს.\n'
        f'- **Open-Meteo:** {FORECAST.label}, 10/80/120/180 მ; {REANALYSIS.label}, 10/100 მ. ეს მოდელური ქარია - '
        'არა გაზომვა და არა გენერაციის პროგნოზი. ქარის სიჩქარის ზრდა გენერაციის პროპორციულ ზრდას არ ნიშნავს.\n'
        '- **ისტორია:** GitHub Actions-ის დაგეგმილი შემგროვებელი ინახავს ყოველ 3-წუთიან პერიოდს ცალკე `data` ტოტზე და ყოველ '
        'გაშვებაზე ავსებს ბოლო 12 საათის გამოტოვებულ პერიოდებს. გამოუქვეყნებელი პერიოდები ხარვეზად რჩება; არაფერი ივსება.\n'
        '- დრო ნაჩვენებია თბილისის დროით (UTC+4); შენახული მონაცემები UTC-შია.',
        '- **GSE:** national aggregate wind generation, 3-minute average, MW, from the public files of the Georgian State '
        'Electrosystem. Source timestamp and quality code are shown as published. Codes other than ACT are flagged as '
        'unverified; the value is neither dropped nor corrected. GSE does not publish per-plant output.\n'
        f'- **Open-Meteo:** {FORECAST.label} at 10/80/120/180 m; {REANALYSIS.label} at 10/100 m. Model wind - not '
        'observations and not a generation forecast. Higher wind speed does not imply proportionally higher generation.\n'
        '- **History:** a scheduled GitHub Actions collector stores every 3-minute period on a separate `data` branch and '
        'backfills missed periods of the last 12 hours on each run. Unpublished periods stay gaps; nothing is filled.\n'
        '- Times are shown in Tbilisi time (UTC+4); stored data is UTC.'))
    st.warning(tr('დამოუკიდებელი საინფორმაციო პროექტი. არ არის GSE-ის ან სხვა ორგანიზაციის ოფიციალური სერვისი და მათ მიერ მოწონებული არ არის. '
                  'არ ასრულებს SCADA-ს, ოპერატიული დისპეჩერიზაციის ან ელექტროენერგეტიკული უსაფრთხოების მართვის ფუნქციას.',
                  'Independent informational project. Not an official service of, or endorsed by, GSE or any other organisation. '
                  'It has no SCADA, operational dispatching or grid-security function.'))
    st.caption(tr('ჰოსტინგი: Streamlit Community Cloud; მოქმედებს პროვაიდერის კონფიდენციალურობის პოლიტიკა. აპლიკაცია ანალიტიკას არ ამატებს. '
                  'რუკის ფონი: OpenFreeMap / OpenMapTiles / OpenStreetMap.',
                  "Hosting: Streamlit Community Cloud; the provider's privacy policy applies. The app adds no analytics. "
                  'Basemap: OpenFreeMap / OpenMapTiles / OpenStreetMap.'))
    st.markdown('[GSE](https://www.gse.com.ge/) · [Open-Meteo (CC BY 4.0)](https://open-meteo.com/) · '
                '[Source methodology](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/tree/main/docs/sources) · '
                '[Data (CSV)](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/tree/data/gse)')


if __name__ == '__main__':
    main()
