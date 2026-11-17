"""Visual layer: dark analytics theme, KPI cards, badges and the shared Plotly style.

All dynamic text inserted into HTML goes through html.escape (values can come from upstream files).
"""

from __future__ import annotations

import html

import plotly.graph_objects as go
import streamlit as st

C = dict(
    bg="#07111c", panel="#0d1a28", panel2="#112236", border="#1c3349", text="#e8f1f8", muted="#8ea4b8",
    accent="#2dd4bf", accent2="#38bdf8", warn="#f5b84a", bad="#f87171", model="#a78bfa", grid="#1a2c3f",
)

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Georgian:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');
:root {{ --wc-accent: {C['accent']}; }}
html, body, [class*="css"], .stMarkdown, .stText, button, input, label, textarea {{
  font-family: 'Inter', 'Noto Sans Georgian', system-ui, sans-serif !important; }}
.stApp {{ background: radial-gradient(1200px 600px at 10% -10%, #0f2a3f 0%, {C['bg']} 55%) fixed; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: {C['panel']}; border-right: 1px solid {C['border']}; }}
.block-container {{ padding-top: 1.6rem; max-width: 1320px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
h2 {{ font-size: 1.25rem !important; font-weight: 600 !important; margin-top: 1.4rem !important; }}
.wc-hero {{ display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap;
  padding: 1.1rem 1.3rem; border:1px solid {C['border']}; border-radius:16px;
  background: linear-gradient(135deg, rgba(45,212,191,0.10), rgba(56,189,248,0.04) 45%, rgba(13,26,40,0.9)); }}
.wc-hero h1 {{ font-size:1.7rem; margin:0; font-weight:700; color:{C['text']}; }}
.wc-hero p {{ margin:.2rem 0 0 0; color:{C['muted']}; font-size:.92rem; }}
.wc-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:.8rem; margin:.9rem 0; }}
.wc-card {{ background:{C['panel']}; border:1px solid {C['border']}; border-radius:14px; padding:.9rem 1rem; min-height:104px; }}
.wc-card.accent {{ border-color: rgba(45,212,191,.55); box-shadow: 0 0 0 1px rgba(45,212,191,.15) inset; }}
.wc-label {{ color:{C['muted']}; font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; font-weight:600; }}
.wc-value {{ color:{C['text']}; font-size:1.75rem; font-weight:700; line-height:1.2; margin-top:.25rem; font-variant-numeric: tabular-nums; }}
.wc-value small {{ font-size:.95rem; color:{C['muted']}; font-weight:500; margin-left:.25rem; }}
.wc-sub {{ color:{C['muted']}; font-size:.8rem; margin-top:.3rem; }}
.wc-up {{ color:{C['accent']}; }} .wc-down {{ color:{C['bad']}; }}
.wc-badge {{ display:inline-flex; align-items:center; gap:.4rem; padding:.28rem .7rem; border-radius:999px; font-size:.8rem; font-weight:600;
  border:1px solid {C['border']}; background:{C['panel2']}; color:{C['text']}; white-space:nowrap; }}
.wc-dot {{ width:.55rem; height:.55rem; border-radius:50%; display:inline-block; }}
.wc-panel {{ background:{C['panel']}; border:1px solid {C['border']}; border-radius:14px; padding:.8rem 1rem; margin:.4rem 0 .8rem 0; }}
.wc-note {{ color:{C['muted']}; font-size:.8rem; }}
.wc-tag {{ display:inline-block; font-size:.7rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; padding:.15rem .5rem;
  border-radius:6px; margin-right:.4rem; }}
.wc-tag.off {{ background: rgba(45,212,191,.14); color:{C['accent']}; }}
.wc-tag.est {{ background: rgba(167,139,250,.16); color:{C['model']}; }}
.wc-tag.mdl {{ background: rgba(56,189,248,.14); color:{C['accent2']}; }}
[data-testid="stMetric"] {{ background:{C['panel']}; border:1px solid {C['border']}; border-radius:12px; padding:.6rem .8rem; }}
@media (max-width: 640px) {{
  .wc-hero h1 {{ font-size:1.35rem; }} .wc-value {{ font-size:1.45rem; }}
  .block-container {{ padding-left:.8rem; padding-right:.8rem; }}
  .wc-badge {{ white-space:normal; }}  /* long source names must wrap, not be clipped */
}}
</style>
"""

STATE_COLOR = {"fresh": C["accent"], "unverified": C["warn"], "stale": C["warn"], "unavailable": C["muted"]}


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def hero(title: str, subtitle: str, badge_html: str = "") -> None:
    st.markdown(f'<div class="wc-hero"><div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>{badge_html}</div>',
                unsafe_allow_html=True)


def badge(text: str, state: str) -> str:
    return (f'<span class="wc-badge"><span class="wc-dot" style="background:{STATE_COLOR.get(state, C["muted"])}"></span>'
            f'{esc(text)}</span>')


def card(label: str, value: str, unit: str = "", sub: str = "", accent: bool = False, sub_class: str = "") -> str:
    unit_html = f"<small>{esc(unit)}</small>" if unit else ""
    sub_html = f'<div class="wc-sub {esc(sub_class)}">{esc(sub)}</div>' if sub else ""
    return (f'<div class="wc-card{" accent" if accent else ""}"><div class="wc-label">{esc(label)}</div>'
            f'<div class="wc-value">{esc(value)}{unit_html}</div>{sub_html}</div>')


def cards(items: list[str]) -> None:
    st.markdown(f'<div class="wc-grid">{"".join(items)}</div>', unsafe_allow_html=True)


def tag(text: str, kind: str) -> str:
    return f'<span class="wc-tag {esc(kind)}">{esc(text)}</span>'


def note(text: str, tags: str = "") -> None:
    st.markdown(f'<div class="wc-note">{tags}{esc(text)}</div>', unsafe_allow_html=True)


def style(fig: go.Figure, height: int = 340, y_title: str = "", x_title: str = "") -> go.Figure:
    fig.update_layout(
        template="plotly_dark", height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Noto Sans Georgian, sans-serif", color=C["text"], size=12),
        margin=dict(l=8, r=8, t=36, b=8), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor=C["grid"], zeroline=False, title=x_title),
        yaxis=dict(gridcolor=C["grid"], zeroline=False, title=y_title),
    )
    return fig


def chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def fmt(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:,.{digits}f}".replace(",", " ")
