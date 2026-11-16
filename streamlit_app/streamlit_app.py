"""Georgia WindCast - Streamlit demo (latest data only).

Run locally:  streamlit run streamlit_app/streamlit_app.py
Deploy:       Streamlit Community Cloud, main file ``streamlit_app/streamlit_app.py`` (docs/STREAMLIT.md)

This is a reduced, database-free edition of the full product: it shows the latest GSE national wind
aggregate with a short in-memory window (no stored history) and the current Open-Meteo forecast.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from windcast_demo import core

logging.basicConfig(level=logging.INFO)

T = {
    "ka": {
        "lang": "ენა",
        "title": "Georgia WindCast",
        "subtitle": "ქარის გენერაცია და მეტეოროლოგიური პირობები საქართველოში",
        "demo": (
            "**საჩვენებელი ვერსია (დემო).** ნაჩვენებია მხოლოდ უახლესი მონაცემები: GSE-ის ბოლო "
            "{hours} საათი, რომელიც აპლიკაციის მეხსიერებაში გროვდება და გადატვირთვისას "
            "იწყება თავიდან. სრული ისტორია და მონაცემთა ბაზა ძირითად ვერსიაშია."
        ),
        "gse_header": "ქარის ჯამური გენერაცია (GSE)",
        "gse_metric": "ბოლო 3-წუთიანი საშუალო",
        "label": "GSE-ის დროის ნიშნული",
        "quality": "ხარისხის კოდი",
        "status": {
            "fresh": "აქტუალური",
            "unverified": "დაუდასტურებელი (ხარისხი ≠ ACT)",
            "stale": "მოძველებული",
            "unavailable": "მიუწვდომელი",
        },
        "gse_error": "GSE-ის მონაცემები დროებით მიუწვდომელია ({code}). ხელახლა ვცდით ავტომატურად.",
        "gaps": "ხარვეზები: {n} პერიოდი არ გამოქვეყნებულა ან ჯერ არ არის ხელმისაწვდომი.",
        "no_gse": "GSE-ის მონაცემები ჯერ არ არის.",
        "mw": "MW",
        "time": "დრო (თბილისი)",
        "fc_header": "ქარის პროგნოზი ლოკაციებზე (მოდელი)",
        "fc_note": (
            "მოდელის პროდუქტი ({model}), არ არის ანემომეტრის გაზომვა და არ არის MW პროგნოზი. "
            "გაშვება: {run} (თბილისი)."
        ),
        "fc_error": "პროგნოზი დროებით მიუწვდომელია ({code}).",
        "fc_kept": "განახლება ვერ მოხერხდა ({code}); ნაჩვენებია ბოლო მიღებული პროგნოზი.",
        "site": "ლოკაცია",
        "height": "სიმაღლე",
        "speed": "ქარის სიჩქარე, მ/წმ",
        "direction": "მიმართულება, °",
        "map_header": "ლოკაციები",
        "map_note": "წერტილები ასახავს სადგურის ტერიტორიას და არა ტურბინებს. სადგურების გენერაციას GSE არ აქვეყნებს.",
        "tz": "დრო მითითებულია თბილისის დროით (UTC+04:00).",
        "about": "მონაცემების შესახებ, წყაროები და დამოუკიდებლობა",
        "about_body": [
            "ქარის ჯამური გენერაცია (MW) აღებულია სს „საქართველოს სახელმწიფო ელექტროსისტემის“ (GSE) "
            "საჯარო 3-წუთიანი მონაცემებიდან. GSE ცალკეული სადგურების გენერაციას არ აქვეყნებს და "
            "აპლიკაცია მას არ აფასებს.",
            "ლოკაციების ქარის მონაცემები: DWD ICON მოდელი Open-Meteo-ს მეშვეობით "
            "(open-meteo.com, CC BY 4.0). ქარის სიჩქარის ზრდა გენერაციის პროპორციულ ზრდას არ ნიშნავს.",
            "ეს ინსტრუმენტი საინფორმაციოა და არ ასრულებს SCADA-ს, ოპერატიული დისპეჩერიზაციის ან "
            "ელექტროენერგეტიკული უსაფრთხოების მართვის ფუნქციას.",
            "დამოუკიდებელი საინფორმაციო პროექტი. არ არის GSE-ის ან სხვა ორგანიზაციის ოფიციალური "
            "სერვისი და მათ მიერ მოწონებული არ არის.",
            "ჰოსტინგი: Streamlit Community Cloud. მოქმედებს ჰოსტინგის პროვაიდერის კონფიდენციალურობის "
            "პოლიტიკა; თავად აპლიკაცია ანალიტიკას არ ამატებს.",
        ],
    },
    "en": {
        "lang": "Language",
        "title": "Georgia WindCast",
        "subtitle": "Wind generation and meteorological conditions in Georgia",
        "demo": (
            "**Demo edition.** Shows the latest data only: the last {hours} hours of GSE data, kept "
            "in the app's memory and restarted when the app restarts. Full history and the database "
            "are in the main edition."
        ),
        "gse_header": "National wind generation (GSE)",
        "gse_metric": "Latest 3-minute average",
        "label": "GSE timestamp",
        "quality": "Quality code",
        "status": {
            "fresh": "Fresh",
            "unverified": "Unverified (quality ≠ ACT)",
            "stale": "Stale",
            "unavailable": "Unavailable",
        },
        "gse_error": "GSE data is temporarily unavailable ({code}). Retrying automatically.",
        "gaps": "Gaps: {n} periods not published or not yet available.",
        "no_gse": "No GSE data yet.",
        "mw": "MW",
        "time": "Time (Tbilisi)",
        "fc_header": "Site wind forecast (model)",
        "fc_note": (
            "Model product ({model}), not an anemometer measurement and not a MW forecast. "
            "Run: {run} (Tbilisi)."
        ),
        "fc_error": "Forecast temporarily unavailable ({code}).",
        "fc_kept": "Refresh failed ({code}); showing the last forecast received.",
        "site": "Site",
        "height": "Height",
        "speed": "Wind speed, m/s",
        "direction": "Direction, °",
        "map_header": "Locations",
        "map_note": "Points represent the wind-farm area, not turbines. GSE does not publish per-plant output.",
        "tz": "Times shown in Tbilisi time (UTC+04:00).",
        "about": "About the data, sources and independence",
        "about_body": [
            "Total wind generation (MW) comes from the public 3-minute data of the Georgian State "
            "Electrosystem (GSE). GSE does not publish per-plant output and this application does "
            "not estimate it.",
            "Site wind: DWD ICON model via Open-Meteo (open-meteo.com, CC BY 4.0). Higher wind speed "
            "does not imply proportionally higher generation.",
            "This tool is informational. It has no SCADA, operational dispatching or grid-security "
            "function.",
            "Independent informational project. Not an official service of, or endorsed by, GSE or "
            "any other organisation.",
            "Hosted on Streamlit Community Cloud; the hosting provider's privacy policy applies. The "
            "app itself adds no analytics.",
        ],
    },
}

STATUS_ICON = {"fresh": "🟢", "unverified": "🟡", "stale": "🟠", "unavailable": "⚪"}
WINDOW_HOURS = 3


def _setting(name: str) -> str | None:
    """Optional, non-secret setting from Streamlit secrets or the environment."""
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets file is fine
        value = None
    return value or os.environ.get(name) or None


@st.cache_resource
def gse_window() -> core.GseRecentWindow:
    ua = _setting("WINDCAST_GSE_USER_AGENT")
    return core.GseRecentWindow(lambda: core.gse_client(ua), window_periods=WINDOW_HOURS * 20)


@st.cache_resource
def forecast_cache() -> core.ForecastCache:
    ua = _setting("WINDCAST_WEATHER_USER_AGENT")
    return core.ForecastCache(lambda: core.weather_client(ua))


def local(t: datetime) -> datetime:
    return t.astimezone(core.SOURCE_TZ)


def wall(t: datetime) -> datetime:
    """Naive Tbilisi wall-clock time: Vega-Lite then shows it as is, whatever the viewer's zone."""
    return local(t).replace(tzinfo=None)


def fmt(t: datetime) -> str:
    return local(t).strftime("%d.%m.%Y %H:%M")


def main() -> None:
    st.set_page_config(page_title="Georgia WindCast (demo)", page_icon="🌬️", layout="wide")
    lang = st.sidebar.radio(
        "ენა / Language", ["ka", "en"], format_func=lambda x: {"ka": "ქართული", "en": "English"}[x]
    )
    t = T[lang]
    now = datetime.now(UTC)

    st.title(t["title"])
    st.caption(t["subtitle"])
    st.info(t["demo"].format(hours=WINDOW_HOURS))

    # ---- GSE national aggregate
    st.header(t["gse_header"])
    snap = gse_window().snapshot(now)
    if snap.error:
        st.warning(t["gse_error"].format(code=snap.error))
    if snap.latest is None:
        st.write(t["no_gse"])
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric(t["gse_metric"], f"{snap.latest.value_mw:,.1f} {t['mw']}")
        c2.metric(t["label"], fmt(snap.latest.period_label_utc))
        c3.metric(t["quality"], snap.latest.quality)
        st.markdown(f"{STATUS_ICON[snap.status]} **{t['status'][snap.status]}**")
        df = pd.DataFrame(
            {
                "time": [wall(p.label_utc) for p in snap.points],
                "mw": [p.value_mw for p in snap.points],
            }
        )
        chart = (
            alt.Chart(df)
            .mark_line(point=alt.OverlayMarkDef(size=12))
            .encode(
                x=alt.X("time:T", title=t["time"], axis=alt.Axis(format="%H:%M")),
                y=alt.Y("mw:Q", title=t["mw"]),
                tooltip=[
                    alt.Tooltip("time:T", format="%d.%m %H:%M"),
                    alt.Tooltip("mw:Q", format=".1f"),
                ],
            )
        )
        st.altair_chart(chart, width="stretch")
        gaps = sum(p.value_mw is None for p in snap.points)
        if gaps:
            st.caption(t["gaps"].format(n=gaps))

    # ---- Forecast
    st.header(t["fc_header"])
    data, err = forecast_cache().get(now)
    status = core.forecast_status(data, now)
    if data is None or status == "unavailable":
        st.warning(t["fc_error"].format(code=err or "expired"))
    else:
        st.markdown(f"{STATUS_ICON[status]} **{t['status'][status]}**")
        if err:
            st.caption(t["fc_kept"].format(code=err))
        st.caption(t["fc_note"].format(model=data.model_label, run=fmt(data.run_time)))
        sites = {s.id: (s.name_ka if lang == "ka" else s.name_en) for s in core.SITES}
        c1, c2 = st.columns(2)
        site_id = c1.selectbox(t["site"], list(sites), format_func=sites.get)
        heights = sorted({r.height_m for r in data.rows})
        height = c2.selectbox(
            t["height"],
            heights,
            index=heights.index(120) if 120 in heights else 0,
            format_func=lambda h: f"{h} m",
        )
        start, end = now - timedelta(hours=6), now + timedelta(hours=72)
        rows = [
            r
            for r in data.rows
            if r.site_id == site_id and r.height_m == height and start <= r.valid_at <= end
        ]
        df = pd.DataFrame(
            {
                "time": [wall(r.valid_at) for r in rows],
                "speed": [r.speed_ms for r in rows],
                "direction": [r.direction_deg for r in rows],
            }
        )
        line = (
            alt.Chart(df)
            .mark_line()
            .encode(
                x=alt.X(
                    "time:T", title=t["time"], axis=alt.Axis(format="%d.%m %H:%M", labelAngle=0)
                ),
                y=alt.Y("speed:Q", title=t["speed"]),
                tooltip=[
                    alt.Tooltip("time:T", format="%d.%m %H:%M"),
                    alt.Tooltip("speed:Q", format=".1f", title=t["speed"]),
                    alt.Tooltip("direction:Q", format=".0f", title=t["direction"]),
                ],
            )
        )
        now_rule = (
            alt.Chart(pd.DataFrame({"time": [wall(now)]}))
            .mark_rule(strokeDash=[4, 4])
            .encode(x="time:T")
        )
        st.altair_chart(line + now_rule, width="stretch")

    # ---- Map
    st.header(t["map_header"])
    st.map(
        pd.DataFrame(
            {"lat": [s.latitude for s in core.SITES], "lon": [s.longitude for s in core.SITES]}
        ),
        zoom=8,
    )
    for s in core.SITES:
        name = s.name_ka if lang == "ka" else s.name_en
        status_txt = s.status_ka if lang == "ka" else s.status_en
        st.markdown(f"- **{name}**: {status_txt}")
    st.caption(t["map_note"])

    st.divider()
    st.caption(t["tz"])
    with st.expander(t["about"]):
        for para in t["about_body"]:
            st.write(para)


main()
