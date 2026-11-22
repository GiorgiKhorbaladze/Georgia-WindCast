"""Streamlit page "ქარის გენერაციის ისტორია / Wind Generation History" (Issue #52).

Monthly energy (GWh) per wind farm. Official, owner-compiled and missing values are always shown
apart: solid bars are confirmed by an official document, hatched bars are owner-compiled and
unverified, and an empty month means no data (never zero).
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui
import wind_history as wh
import wind_history_view as v
from history import DATA_BASE
from i18n import tr

MONTHS = {
    "ka": ["იან", "თებ", "მარ", "აპრ", "მაი", "ივნ", "ივლ", "აგვ", "სექ", "ოქტ", "ნოე", "დეკ"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
TTL = timedelta(hours=6)  # the monitor checks GSE at most every 20 days (owner decision 20.11.2026); a few hours of cache is ample


@st.cache_data(ttl=TTL, show_spinner=False)
def _load(base: str) -> v.Loaded:
    return v.load(base)


def name(sid: str, lang: str) -> str:
    st_ = wh.STATION_BY_ID[sid]
    return st_.name_ka if lang == "ka" else st_.name_en


def label(year: int, month: int, lang: str) -> str:
    return f"{MONTHS[lang][month - 1]} {year}"


def gwh(value: float | None, digits: int = 2) -> str:
    return ui.fmt(value, digits)


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:+.1f}%"


def status_text(row, lang: str) -> str:
    if row.official:
        return tr("wh_status_official", lang)
    if row.conflict:
        return tr("wh_status_conflict", lang)
    return tr("wh_status_unverified", lang)


def render(lang: str) -> None:
    ui.hero(tr("page_wind_history", lang), tr("wh_subtitle", lang))
    loaded = _load(DATA_BASE)
    df = v.frame(loaded.records)
    if df.empty:
        st.info(tr("wh_empty", lang))
        return
    ui.note(tr("wh_energy_note", lang))
    origin = tr("wh_origin_archive" if loaded.origin == "archive" else "wh_origin_seed", lang)
    st.caption(origin)
    if loaded.error:
        st.warning(tr("wh_origin_error", lang))
    kpis(df, lang)
    st.caption(tr("wh_legend", lang))

    st.subheader(tr("wh_monthly", lang))
    years = sorted(df.year.unique(), reverse=True)
    all_st = v.stations_in(df)
    c1, c2, c3 = st.columns([1, 2, 1])
    year = c1.selectbox(tr("wh_year", lang), years, key="wh_year")
    chosen = c2.multiselect(tr("wh_stations", lang), all_st, default=all_st, key="wh_st",
                            format_func=lambda s: name(s, lang)) or all_st
    stacked = c3.toggle(tr("wh_stacked", lang), value=True, key="wh_stack")
    ui.chart(monthly_figure(df, year, chosen, stacked, lang))
    missing = missing_months(df, year, chosen)
    if missing:
        ui.note(tr("wh_no_data_months", lang, months=", ".join(MONTHS[lang][m - 1] for m in missing)))

    st.subheader(tr("wh_annual", lang))
    ann = v.annual(df[df.station_id.isin(chosen)])
    ui.chart(annual_figure(ann, lang))
    partial = sorted(int(y) for y in ann[~ann.complete].year.unique())
    if partial:
        ui.note(tr("wh_partial_note", lang, years=", ".join(map(str, partial))))

    left, right = st.columns(2)
    with left:
        st.subheader(tr("wh_heatmap", lang))
        ui.chart(heatmap_figure(df, chosen, lang))
        ui.note(tr("wh_heatmap_note", lang))
    with right:
        st.subheader(tr("wh_yoy", lang))
        ui.chart(yoy_figure(df[df.station_id.isin(chosen)], year, lang))
        ui.note(tr("wh_yoy_note", lang))

    st.subheader(tr("wh_cumulative", lang))
    picks = st.multiselect(tr("wh_years", lang), sorted(df.year.unique()), default=years[:3], key="wh_cum")
    ui.chart(cumulative_figure(df, picks, chosen, lang))
    ui.note(tr("wh_cum_note", lang))

    st.subheader(tr("wh_coverage", lang))
    for c in v.coverage(df):
        gaps = ", ".join(label(y, m, lang) for y, m in c.gaps) or tr("wh_none", lang)
        st.markdown(f"- {ui.esc(tr('wh_cov_row', lang, name=name(c.station_id, lang), first=label(*c.first, lang), last=label(*c.last, lang), n=c.months, gaps=gaps))}")

    st.subheader(tr("wh_table", lang))
    shown = df[df.station_id.isin(chosen)].sort_values(["period", "station_id"], ascending=[False, True])
    table = pd.DataFrame({
        tr("wh_col_station", lang): shown.station_id.map(lambda s: name(s, lang)),
        tr("wh_col_period", lang): [f"{y}-{m:02d}" for y, m in zip(shown.year, shown.month, strict=True)],
        tr("wh_col_gwh", lang): shown.gwh.round(3),
        tr("wh_col_status", lang): [status_text(r, lang) for r in shown.itertuples()],
        tr("wh_col_source", lang): shown.source_kind.map(
            {"owner_workbook": tr("wh_src_owner", lang), "gse_balance_pdf": tr("wh_src_pdf", lang)}),
    })
    st.dataframe(table, hide_index=True, width="stretch", height=320)
    d1, d2 = st.columns(2)
    d1.download_button(tr("wh_csv", lang), v.to_csv(shown), "wind_monthly_gwh.csv", "text/csv", key="wh_csv")
    d2.download_button(tr("wh_xlsx", lang), v.to_xlsx(shown), "wind_monthly_gwh.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="wh_xlsx")
    ui.note(tr("wh_method", lang))


def kpis(df: pd.DataFrame, lang: str) -> None:
    last = v.latest_period(df)
    ly, lm = v.ym(last)
    latest = df[df.period == last]
    gaps = v.fleet_month_missing(df, last)
    latest_sub = tr("wh_k_latest_sub", lang, n=len(latest))
    if gaps:
        latest_sub += " · " + tr("wh_k_latest_missing", lang, names=", ".join(name(s, lang) for s in gaps))
    cards = [ui.card(tr("wh_k_latest", lang) + f" ({label(ly, lm, lang)})", gwh(latest.gwh.sum()), "GWh",
                     latest_sub, accent=True)]
    year = v.latest_complete_year(df)
    if year is not None:
        cards.append(ui.card(tr("wh_k_year", lang, year=year), gwh(df[df.year == year].gwh.sum()), "GWh"))
    yoy = v.ytd_yoy(df, ly, lm)
    span = f"{MONTHS[lang][0]}-{MONTHS[lang][lm - 1]} {ly}" if lm > 1 else label(ly, 1, lang)
    cards.append(ui.card(tr("wh_k_ytd", lang, span=span), gwh(yoy.current), "GWh"))
    if yoy.change_pct is not None:
        sub = tr("wh_k_yoy_sub", lang, ex=pct(yoy.existing_pct), new=gwh(yoy.new_contribution))
        cards.append(ui.card(tr("wh_k_yoy", lang), pct(yoy.change_pct), "", sub,
                             sub_class="wc-up" if yoy.change_pct >= 0 else "wc-down"))
    cards.append(ui.card(tr("wh_k_farms", lang), str(len(v.stations_in(df))), "",
                         ", ".join(name(s, lang) for s in v.stations_in(df))))
    share = df.official.mean() * 100
    first = v.ym(int(df.period.min()))
    cards.append(ui.card(tr("wh_k_cov", lang), f"{share:.0f}%", "",
                         tr("wh_k_cov_sub", lang, first=label(*first, lang), last=label(ly, lm, lang), months=len(df))))
    ui.cards(cards)


def missing_months(df: pd.DataFrame, year: int, stations: list[str]) -> list[int]:
    have = set(df[(df.year == year) & df.station_id.isin(stations)].month)
    return [m for m in range(1, 13) if m not in have]


def _bar_style(rows: pd.DataFrame, sid: str):
    color = wh.STATION_BY_ID[sid].color
    shapes = ["" if o else "/" for o in rows.official]
    return dict(color=color, pattern=dict(shape=shapes, fgcolor="rgba(7,17,28,.55)", solidity=0.35),
                line=dict(color=["#f5b84a" if c else color for c in rows.conflict], width=1))


def monthly_figure(df, year, stations, stacked, lang) -> go.Figure:
    fig = go.Figure()
    x = MONTHS[lang]
    for sid in stations:
        rows = df[(df.year == year) & (df.station_id == sid)].set_index("month").reindex(range(1, 13))
        present = rows.gwh.notna()
        sub = rows[present]
        if sub.empty:
            continue
        fig.add_bar(x=[x[m - 1] for m in sub.index], y=sub.gwh, name=name(sid, lang),
                    marker=_bar_style(sub, sid),
                    customdata=[status_text(r, lang) for r in sub.itertuples()],
                    hovertemplate="%{y:.2f} GWh · %{customdata}<extra>" + ui.esc(name(sid, lang)) + "</extra>")
    fig.update_layout(barmode="stack" if stacked else "group")
    fig.update_xaxes(categoryorder="array", categoryarray=x)
    return ui.style(fig, 340, "GWh")


def annual_figure(ann: pd.DataFrame, lang: str) -> go.Figure:
    fig = go.Figure()
    for sid in v.stations_in(ann) if not ann.empty else []:
        rows = ann[ann.station_id == sid]
        fig.add_bar(x=rows.year.astype(str), y=rows.gwh.round(2), name=name(sid, lang),
                    marker=dict(color=wh.STATION_BY_ID[sid].color, opacity=[1 if c else 0.45 for c in rows.complete],
                                pattern=dict(shape=["" if c else "x" for c in rows.complete], solidity=0.2)),
                    customdata=[f"{m}/12" for m in rows.months],
                    hovertemplate="%{y:.2f} GWh · %{customdata}<extra>" + ui.esc(name(sid, lang)) + "</extra>")
    totals = ann.groupby("year").agg(gwh=("gwh", "sum"), complete=("complete", "first")).reset_index()
    fig.add_scatter(x=totals.year.astype(str), y=totals.gwh, mode="text", showlegend=False, hoverinfo="skip",
                    text=[f"{g:.1f}" + ("" if c else "*") for g, c in zip(totals.gwh, totals.complete, strict=True)],
                    textposition="top center", textfont=dict(size=11, color=ui.C["muted"]))
    fig.update_layout(barmode="stack")
    return ui.style(fig, 360, "GWh")


def heatmap_figure(df, stations, lang) -> go.Figure:
    m = v.month_matrix(df, stations)
    z = m.values
    text = [["" if pd.isna(val) else f"{val:.1f}" for val in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=MONTHS[lang], y=[str(y) for y in m.index], text=text, texttemplate="%{text}", hoverongaps=False,
        colorscale=[[0, "#0f2a3f"], [0.5, "#1f8f86"], [1, "#9cf3e2"]], colorbar=dict(title="GWh"),
        hovertemplate="%{y} %{x}: %{z:.2f} GWh<extra></extra>"))
    fig.update_yaxes(autorange="reversed", type="category")
    return ui.style(fig, 30 * len(m.index) + 120)


def yoy_figure(df, year, lang) -> go.Figure:
    t = v.monthly_yoy(df, year)
    fig = go.Figure()
    fig.add_bar(x=MONTHS[lang], y=t.existing_delta, name=tr("wh_yoy_existing", lang), marker_color=ui.C["accent2"],
                hovertemplate="%{y:+.2f} GWh<extra></extra>")
    fig.add_bar(x=MONTHS[lang], y=t.new_farms.where(t.new_farms > 0), name=tr("wh_yoy_new", lang),
                marker_color=ui.C["warn"], hovertemplate="+%{y:.2f} GWh<extra></extra>")
    fig.update_layout(barmode="relative")
    return ui.style(fig, 300, "Δ GWh")


def cumulative_figure(df, years, stations, lang) -> go.Figure:
    fig = go.Figure()
    for i, year in enumerate(sorted(years, reverse=True)):
        fig.add_scatter(x=MONTHS[lang], y=v.cumulative(df, year, stations), name=str(year), mode="lines+markers",
                        connectgaps=False, line=dict(width=3 if i == 0 else 1.6),
                        hovertemplate="%{x}: %{y:.1f} GWh<extra>" + str(year) + "</extra>")
    return ui.style(fig, 320, "GWh")
