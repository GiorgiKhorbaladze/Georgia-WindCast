"""Georgia WindCast - on-demand Community Cloud pilot, using reviewed source parsers."""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data import FORECAST, REANALYSIS, SITES, SourceCache, generation_state, weather_state

st.set_page_config(page_title='Georgia WindCast', page_icon='🌬️', layout='wide')
TZ = ZoneInfo('Asia/Tbilisi')


@st.cache_resource
def source_cache():
    return SourceCache()


def main():
    language = st.sidebar.radio('ენა / Language', ['ქართული', 'English'])
    ka = language == 'ქართული'
    def tr(ge, en):
        return ge if ka else en
    def local(value):
        return value.astimezone(TZ).strftime('%d.%m.%Y %H:%M')
    states = {'fresh': tr('აქტუალური', 'Fresh'), 'stale': tr('მოძველებული / არასრული', 'Stale / partial'),
              'unavailable': tr('მიუწვდომელია', 'Unavailable'), 'unverified': tr('ხარისხი დაუდასტურებელია', 'Unverified quality')}
    page = st.sidebar.radio(tr('გვერდები', 'Pages'), [tr('მიმოხილვა', 'Overview'), tr('პროგნოზი', 'Forecast'),
                             tr('ისტორია', 'History'), tr('მონაცემების შესახებ', 'About data')])
    st.sidebar.caption('Georgia WindCast · Community Cloud')
    st.sidebar.caption(tr('დრო: თბილისი (UTC+4)', 'Time: Tbilisi (UTC+4)'))
    st.title('Georgia WindCast')
    st.caption(tr('საქართველოს ქარის გენერაცია და მოდელური ქარი', 'Georgia wind generation and modelled wind'))
    st.info(tr('საპილოტე ვერსია: მონაცემები მოწმდება გახსნილი გვერდის დროს. შეგროვებული ისტორია დროებითია და სერვერის გადატვირთვისას იკარგება; უწყვეტი მონიტორინგი არ არის უზრუნველყოფილი.',
               'Pilot: sources are checked while this page is open. Collected history is temporary and is lost on server restart; continuous monitoring is not provided.'))
    if page == tr('მონაცემების შესახებ', 'About data'):
        st.subheader(tr('წყაროები და საზღვრები', 'Sources and limitations'))
        st.markdown(tr('- **სსე:** საქართველოს ქარის სადგურების ჯამური 3-წუთიანი სიმძლავრე, მგვტ. ACT კოდი ნაჩვენებია წყაროს მიხედვით; სხვა კოდის მნიშვნელობა დაუდასტურებელია.\n- **Open-Meteo:** DWD ICON global პროგნოზი, 10/80/120/180 მ; ERA5 რეანალიზი, 10/100 მ. ეს არის მოდელური ქარი, არა გაზომვა ან გენერაციის პროგნოზი.\n- 200 მეტრის მონაცემები არ არის მხარდაჭერილი. გამოტოვებული მნიშვნელობები არ ივსება.\n- ობიექტის წერტილი წარმომადგენლობითია და არა კონკრეტული ტურბინის კოორდინატი.',
                         '- **GSE:** national aggregate wind generation, 3-minute periods, MW. ACT is the source quality code; other codes are unverified.\n- **Open-Meteo:** DWD ICON global forecast at 10/80/120/180 m; ERA5 reanalysis at 10/100 m. Model wind, not observations or generation forecasts.\n- 200 m is unsupported. Missing values are not filled.\n- Site points are representative locations, not turbine coordinates.'))
        st.warning(tr('დამოუკიდებელი საინფორმაციო პროექტი. არ არის სსე-ის ოფიციალური სერვისი და არ გამოიყენება ოპერატიული მართვისთვის.',
                      'Independent informational project. Not an official GSE service and not for operational decisions.'))
        st.markdown('[GSE](https://www.gse.com.ge/) · [Open-Meteo](https://open-meteo.com/) · [Source methodology](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/tree/main/docs/sources)')
        return

    @st.fragment(run_every=180)
    def dashboard():
        now = datetime.now(UTC)
        data = source_cache().snapshot(now, include_archive=page == tr('ისტორია', 'History'))
        for source, error in data['errors'].items():
            st.warning(tr(f'{source}: განახლება ვერ შესრულდა ({error}); დროები და სტატუსები გადაამოწმეთ.',
                          f'{source}: refresh failed ({error}); check source timestamps and status.'))
        st.caption(tr('ბოლო შემოწმება: ', 'Last check: ') + local(now))
        if page == tr('მიმოხილვა', 'Overview'):
            latest = data['history'][-1] if data['history'] else None
            state = generation_state(latest, now)
            st.subheader(tr('ქარის ჯამური გენერაცია', 'National wind generation'))
            cols = st.columns(3)
            cols[0].metric(tr('სსე · მგვტ', 'GSE · MW'), f"{latest['value_mw']:.2f}" if latest and state != 'unverified' else '-')
            cols[1].metric(tr('მდგომარეობა', 'Status'), states[state])
            cols[2].metric(tr('წყაროს დრო', 'Source time'), local(latest['time']) if latest else '-')
            if latest:
                st.caption(f"QUALITY: {latest['quality']} · " + tr('მიღებულია: ', 'Retrieved: ') + local(latest['retrieved']))
                with st.expander(tr('წყაროს ჩანაწერი', 'Source record')):
                    st.json({k: str(v) for k, v in latest.items()})
            st.subheader(tr('ქარის ობიექტები', 'Wind sites'))
            st.map(pd.DataFrame([dict(lat=s.latitude, lon=s.longitude) for s in SITES]))
            for i, site in enumerate(SITES):
                packet = data['forecast']
                wstate, hours = weather_state(packet, now, i, 80)
                hour = now.replace(minute=0, second=0, microsecond=0)
                current = next((v for v in packet['series'][i].by_height[80] if v.valid_at == hour), None) if packet else None
                value = f'{current.speed_ms:.1f} m/s' if current and current.speed_ms is not None else '-'
                st.write(f"**{site.name_ka if ka else site.name_en}** · 80 m · {value} · {states[wstate]}")
                if current:
                    st.caption(tr('მოდელური საათი: ', 'Model valid hour: ') + local(current.valid_at))
            st.caption(FORECAST.label)
        elif page == tr('პროგნოზი', 'Forecast'):
            idx = st.selectbox(tr('ობიექტი', 'Site'), range(len(SITES)), format_func=lambda i: SITES[i].name_ka if ka else SITES[i].name_en)
            height = st.selectbox(tr('სიმაღლე, მ', 'Height, m'), FORECAST.heights, index=1)
            packet = data['forecast']
            state, hours = weather_state(packet, now, idx, height)
            st.caption(FORECAST.label + ' · ' + states[state])
            if not packet:
                st.info(tr('პროგნოზი ჯერ მიუწვდომელია.', 'Forecast is currently unavailable.'))
                return
            st.caption(tr('მოდელის გაშვება: ', 'Model run: ') + local(packet['run']) + ' · ' + tr('მიღებულია: ', 'Retrieved: ') + local(packet['retrieved']))
            st.caption(tr(f'უწყვეტი წინმსწრები დაფარვა: {hours} საათი (არაუმეტეს 72 სთ).', f'Continuous forward coverage: {hours} hours (up to 72 h).'))
            values = [v for v in packet['series'][idx].by_height[height] if now.replace(minute=0, second=0, microsecond=0) <= v.valid_at <= now + timedelta(hours=72)]
            show_series(values, tr, local, 'Forecast')
        else:
            st.subheader(tr('დროებით შეგროვებული გენერაცია', 'Temporarily collected generation'))
            st.caption(tr('ეს არ არის სრული არქივი. წერტილებს შორის ხაზები არ იხაზება, რადგან გამოტოვებული პერიოდები შეიძლება არსებობდეს.', 'This is not a complete archive. Points are not joined because collection gaps may exist.'))
            history = data['history']
            if history:
                frame = pd.DataFrame(history)
                figure = go.Figure()
                for quality in frame.quality.unique():
                    subset = frame[frame.quality == quality]
                    figure.add_scatter(x=[t.astimezone(TZ).strftime('%Y-%m-%dT%H:%M:%S') for t in subset.time], y=subset.value_mw,
                                       mode='markers', name=f'QUALITY: {quality}')
                figure.update_layout(yaxis_title=tr('მგვტ', 'MW'), xaxis_title='Asia/Tbilisi', xaxis_type='date', height=350)
                st.plotly_chart(figure, use_container_width=True)
                st.download_button(tr('CSV ჩამოტვირთვა (UTC)', 'Download CSV (UTC)'), frame.to_csv(index=False), 'windcast_observed_history.csv', 'text/csv')
            else:
                st.info(tr('ჩანაწერები ჯერ არ არის.', 'No readings collected yet.'))
            st.subheader(tr('ERA5 რეანალიზი', 'ERA5 reanalysis'))
            st.caption(REANALYSIS.label + ' · ' + tr('ბოლო 7 დღე, 5-დღიანი დაყოვნებით; არა გაზომვა.', 'Seven days with a five-day lag; not observations.'))
            archive = data['archive']
            if archive:
                idx = st.selectbox(tr('ობიექტი', 'Site'), range(len(SITES)), format_func=lambda i: SITES[i].name_ka if ka else SITES[i].name_en)
                height = st.selectbox(tr('სიმაღლე, მ', 'Height, m'), REANALYSIS.heights)
                st.caption(tr('მიღებულია: ', 'Retrieved: ') + local(archive['retrieved']))
                show_series(archive['series'][idx].by_height[height], tr, local, 'ERA5')
            else:
                st.info(tr('რეანალიზი მიუწვდომელია.', 'Reanalysis unavailable.'))
    dashboard()


def show_series(values, tr, local, label):
    if not values:
        st.info(tr('მონაცემები არ არის.', 'No data.'))
        return
    # Reindex to hourly resolution: omitted timestamps must create visible gaps too.
    frame = pd.DataFrame([dict(time=v.valid_at, speed=v.speed_ms, direction=v.direction_deg) for v in values]).set_index('time')
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq='h'))
    figure = go.Figure(go.Scatter(x=[t.astimezone(TZ).strftime('%Y-%m-%dT%H:%M:%S') for t in frame.index], y=frame.speed,
                                 mode='lines', connectgaps=False, name=label))
    figure.update_layout(yaxis_title='m/s', xaxis_title='Asia/Tbilisi', xaxis_type='date', height=370)
    st.plotly_chart(figure, use_container_width=True)
    display = frame.copy()
    display.index = [local(t) for t in frame.index]
    display.columns = [tr('სიჩქარე, მ/წმ', 'Speed, m/s'), tr('მიმართულება FROM, °', 'Direction FROM, °')]
    st.dataframe(display, use_container_width=True)


if __name__ == '__main__':
    main()
