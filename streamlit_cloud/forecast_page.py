"""Page "ქარის გენერაციის პროგნოზი / Wind Generation Forecast" (Issue #57, stage I, experimental).

Reads the outputs of .github/workflows/forecast.yml from the `forecast-data` branch. While
``mwmodel.PUBLISH_FORECAST`` is False the page shows only the evaluation of past forecasts
(accuracy against GSE observations) and the timing of the latest issue, never the forecast
values themselves.
"""

from __future__ import annotations

import io
import json
import os
from datetime import timedelta

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import mwmodel
import ui
from i18n import T, tr

BASE = os.environ.get("WINDCAST_FORECAST_BASE_URL",
                      "https://raw.githubusercontent.com/GiorgiKhorbaladze/Georgia-WindCast/forecast-data/")
CADENCES = ("3m", "15m", "1h", "1d", "1mo")
COLORS = {"persistence": "#8ea4b8", "damped_trend": "#2dd4bf", "climatology": "#f5b84a"}


def fetch(path: str, base: str = BASE) -> str | None:
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        resp = client.get(base + path)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


@st.cache_data(ttl=timedelta(minutes=10), show_spinner=False)
def load() -> dict:
    out = {"board": None, "history": None, "day_ahead": None, "tournament": None, "error": None}
    try:
        text = fetch("evaluation/leaderboard.json")
        if text:
            out["board"] = json.loads(text)
            tour = fetch("evaluation/tournament.json")
            out["tournament"] = json.loads(tour) if tour else None
            for key, name in (("history", "history_backtest.csv"), ("history_live", "history_live.csv")):
                body = fetch(f"evaluation/{name}")
                out[key] = _csv(body)
            day = fetch("evaluation/day_ahead_summary_live.json")  # aggregates only; values stay private
            out["day_ahead"] = json.loads(day) if day else None
    except (httpx.HTTPError, ValueError) as exc:
        out["error"] = type(exc).__name__
    return out


def _csv(body: str | None) -> pd.DataFrame | None:
    """An evaluation file with no rows yet is written as an empty CSV: treat it as no data."""
    if not body or not body.strip():
        return None
    try:
        return pd.read_csv(io.StringIO(body))
    except pd.errors.EmptyDataError:
        return None


def model_name(mid: str, lang: str) -> str:
    key = f"fc_m_{mid}"
    return tr(key, lang) if key in T else mid


def horizon_label(minutes: int, lang: str) -> str:
    return f"{minutes} {tr('fc_min', lang)}" if minutes < 60 else f"{minutes // 60} {tr('fc_h', lang)}"


def render(lang: str) -> None:
    ui.hero(tr("page_gen_forecast", lang), tr("fc_subtitle", lang),
            ui.badge(tr("fc_experimental", lang), "unverified"))
    ui.note(tr("fc_withheld", lang) if not mwmodel.PUBLISH_FORECAST else tr("fc_published", lang))
    data = load()
    board = data["board"]
    if data["error"]:
        st.warning(tr("fc_load_error", lang))
    if not board:
        st.info(tr("fc_no_data", lang))
        return
    live = board.get("live", {}).get("coverage", {})
    cards = [ui.card(tr("fc_last_obs", lang), _local(board.get("latest_observation")), "", tr("fc_last_obs_sub", lang)),
             ui.card(tr("fc_evaluated", lang), _local(board.get("generated_at")), ""),
             ui.card(tr("fc_live_count", lang), str(live.get("forecasts", 0)), "",
                     tr("fc_late_share", lang, pct=f"{100 * live.get('late_share', 0):.0f}%"))]
    ui.cards(cards)
    ui.note(tr("fc_late_note", lang))

    cadence = st.radio(tr("fc_cadence", lang), CADENCES, horizontal=True, key="fc_cad",
                       format_func=lambda c: tr(f"fc_c_{c}", lang))
    if cadence == "1mo":
        st.info(tr("fc_monthly_note", lang))
        return
    if cadence == "1d":
        _day_ahead(data["day_ahead"], lang)
        return
    source = st.radio(tr("fc_source", lang), ("backtest", "live"), horizontal=True, key="fc_src",
                      format_func=lambda s: tr(f"fc_src_{s}", lang))
    rows = [r for r in (board.get(source) or {}).get("leaderboard", []) if r["cadence"] == cadence]
    if not rows:
        st.info(tr("fc_no_cases", lang))
        return
    df = pd.DataFrame(rows)
    if (df["evidence"] == "insufficient_evidence").any():
        st.warning(tr("fc_insufficient", lang, days=board.get("min_days"), cases=board.get("min_cases")))
    st.subheader(tr("fc_mae_by_h", lang))
    ui.chart(_mae_chart(df, lang))
    st.subheader(tr("fc_table", lang))
    table = pd.DataFrame({
        tr("fc_col_h", lang): [horizon_label(m, lang) for m in df.horizon_min],
        tr("fc_col_model", lang): [model_name(m, lang) for m in df.model_id],
        "MAE, MW": df.mae.round(2), "RMSE, MW": df.rmse.round(2),
        tr("fc_col_skill", lang): [tr("fc_reference", lang) if m == "persistence" else "-" if s is None else f"{s:+.3f}"
                                   for m, s in zip(df.model_id, df.skill, strict=True)],
        tr("fc_col_ci", lang): ["-" if c is None else f"{c[0]:+.2f} ... {c[1]:+.2f}" for c in df.skill_90ci],
        tr("fc_col_cases", lang): df.cases, tr("fc_col_days", lang): df.days,
        tr("fc_col_evidence", lang): [tr(f"fc_ev_{e}", lang) for e in df.evidence],
    })
    st.dataframe(table, hide_index=True, width="stretch")
    st.download_button(tr("wh_csv", lang), df.drop(columns=["skill_90ci"]).to_csv(index=False).encode("utf-8-sig"),
                       f"forecast_scores_{source}_{cadence}.csv", "text/csv", key="fc_csv")
    hist = data["history"] if source == "backtest" else data.get("history_live")
    if hist is not None and len(hist):
        st.subheader(tr("fc_history", lang))
        ui.chart(_history_chart(hist[hist.cadence == cadence], lang))
    _tournament(data.get("tournament"), lang)
    ui.note(tr("fc_method", lang))


def _local(iso: str | None) -> str:
    if not iso:
        return "-"
    return pd.Timestamp(iso).tz_convert("Asia/Tbilisi").strftime("%d.%m.%Y %H:%M")


def _mae_chart(df: pd.DataFrame, lang: str) -> go.Figure:
    fig = go.Figure()
    for mid, g in df.groupby("model_id"):
        g = g.sort_values("horizon_min")
        fig.add_scatter(x=[horizon_label(m, lang) for m in g.horizon_min], y=g.mae, mode="lines+markers",
                        name=model_name(mid, lang), line=dict(color=COLORS.get(mid)))
    return ui.style(fig, 320, "MAE, MW")


def _history_chart(h: pd.DataFrame, lang: str) -> go.Figure:
    fig = go.Figure()
    first = h.horizon_min.min() if len(h) else None
    for mid, g in h[h.horizon_min == first].groupby("model_id"):
        fig.add_scatter(x=g.day, y=g.mae, mode="lines+markers", name=model_name(mid, lang),
                        line=dict(color=COLORS.get(mid)))
    return ui.style(fig, 280, "MAE, MW")


def _day_ahead(summary: dict | None, lang: str) -> None:
    rows = (summary or {}).get("models") or []
    if not rows:
        st.info(tr("fc_day_none", lang))
        return
    st.dataframe(pd.DataFrame({tr("fc_col_model", lang): [model_name(r["model_id"], lang) for r in rows],
                               "MAE, MWh": [r["mae_mwh"] for r in rows],
                               tr("fc_col_days", lang): [r["days"] for r in rows]}),
                 hide_index=True, width="stretch")


def _tournament(t: dict | None, lang: str) -> None:
    """Daily challenger tournament: hourly cadence, identical independent day folds for every model."""
    if not t:
        return
    st.subheader(tr("fc_tour", lang))
    ui.note(tr("fc_tour_note", lang))
    variants = list((t.get("variants") or {}).keys())
    if not variants:
        return
    name = st.radio(tr("fc_tour_variant", lang), variants, horizontal=True, key="fc_tour_v",
                    format_func=lambda v: _variant_label(v, lang))
    v = t["variants"][name]
    unavailable = [m for m, s in v.get("status", {}).items() if s != "available"]
    if unavailable:
        st.caption(tr("fc_tour_unavail", lang, models=", ".join(f"{m} ({v['status'][m]})" for m in unavailable)))
    rows = v.get("scores") or []
    if not rows:
        st.info(tr("fc_no_cases", lang))
        return
    df = pd.DataFrame(rows)
    st.dataframe(pd.DataFrame({
        tr("fc_col_h", lang): [f"{h} {tr('fc_h', lang)}" for h in df.horizon_h],
        tr("fc_col_model", lang): [model_name(m, lang) for m in df.model_id],
        "MAE, MW": df.mae.round(2), "RMSE, MW": df.rmse.round(2),
        tr("fc_col_skill", lang): [tr("fc_reference", lang) if m == "persistence" else "-" if s is None else f"{s:+.3f}"
                                   for m, s in zip(df.model_id, df.skill, strict=True)],
        tr("fc_col_ci", lang): ["-" if c is None else f"{c[0]:+.2f} ... {c[1]:+.2f}" for c in df.skill_90ci],
        tr("fc_col_cases", lang): df.cases, tr("fc_col_indep", lang): df.independent_days,
        tr("fc_col_evidence", lang): [tr(f"fc_ev_{e}", lang) for e in df.evidence],
    }), hide_index=True, width="stretch")
    if t.get("weather_ablation"):
        st.caption(tr("fc_tour_noweather", lang))


def _variant_label(v: str, lang: str) -> str:
    """'gse_only' or '<source>_<predictor set>' -> readable label (source names stay as in the data)."""
    if f"fc_v_{v}" in T:
        return tr(f"fc_v_{v}", lang)
    for src in ("icon_openmeteo", "gfs", "ecmwf", "visualcrossing"):
        if v.startswith(src + "_") and f"fc_v_{v[len(src) + 1:]}" in T:
            return f"{tr(f'fc_srcname_{src}', lang)}: {tr(f'fc_v_{v[len(src) + 1:]}', lang)}"
    return v
