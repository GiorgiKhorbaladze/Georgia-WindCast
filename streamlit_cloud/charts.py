"""Chart builders for the forecast page. Plotly only, no Streamlit calls, so they are unit-tested.

Times on axes are Tbilisi wall-clock strings, independent of the viewer's time zone.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import compass
import ui
from i18n import tr

TZ = ZoneInfo('Asia/Tbilisi')


def wall(value):
    """Tbilisi wall-clock string for chart axes, independent of the viewer's time zone."""
    return pd.Timestamp(value).tz_convert(TZ).strftime('%Y-%m-%dT%H:%M:%S')


def time_ticks(start, end):
    """Tick positions and labels in Tbilisi time: every 6/12/24 h by span; midnight is labelled by its date.

    Plotly's automatic ticks on a phone-width 3-day axis show only midnights; explicit 12-hour
    ticks keep the hour readable while the date marks each day boundary.
    """
    s, e = pd.Timestamp(start).tz_convert(TZ), pd.Timestamp(end).tz_convert(TZ)
    span = (e - s).total_seconds() / 3600
    step = pd.Timedelta(hours=6 if span <= 36 else 12 if span <= 96 else 24)
    t = s.floor(step)
    t = t if t >= s else t + step
    vals, text = [], []
    while t <= e:
        vals.append(t.strftime('%Y-%m-%dT%H:%M:%S'))
        text.append(t.strftime('%d.%m') if t.hour == 0 else t.strftime('%H:%M'))  # date = 00:00 of that day
        t += step
    return vals, text


def now_marker(fig, now, lang, rows=None):
    """Dotted vertical line at the current time, labelled so it is not mistaken for data.

    rows=True: the line spans the whole figure (stacked panels sharing one x axis).
    """
    x = wall(now)
    if rows:
        fig.add_shape(type='line', x0=x, x1=x, xref='x', y0=0, y1=1, yref='paper',
                      line=dict(dash='dot', color=ui.C['warn'], width=1.5))
        fig.add_annotation(x=x, y=1, yref='paper', text=tr('now', lang), showarrow=False, xanchor='left',
                           yanchor='top', xshift=3, font=dict(color=ui.C['warn'], size=11), bgcolor='rgba(7,17,28,0.85)')
        return
    fig.add_vline(x=x, line_dash='dot', line_color=ui.C['warn'], line_width=1.5)
    fig.add_annotation(x=x, y=1, yref='y domain', text=tr('now', lang), showarrow=False, xanchor='left',
                       yanchor='top', xshift=3, font=dict(color=ui.C['warn'], size=11), bgcolor='rgba(7,17,28,0.85)')


def series_frame(values) -> pd.DataFrame:
    """Model values -> hourly frame (UTC index; columns speed, direction).

    Values are kept exactly as parsed: no smoothing, no interpolation. Missing hours are reindexed
    to NaN so they appear as gaps (connectgaps=False), never as a straight line across the hole.
    """
    frame = pd.DataFrame([dict(time=v.valid_at, speed=v.speed_ms, direction=v.direction_deg) for v in values])
    frame = frame.set_index('time').astype(float)
    return frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq='h'))


def series_figure(frame, lang, height_m=None):
    """Two stacked panels on ONE time axis: speed (line) above, direction FROM (points) below.

    Stacked panels replace the former dual-axis chart, which mixed m/s and degrees in one plot area
    and was hard to read on a phone. Both traces use the same x axis, so one hover shows speed and
    direction for the same hour. Direction is drawn as points only: joining 359° to 1° with a line
    would suggest a 358° swing (circular quantity). Light-wind hours get hollow markers.
    """
    x = [wall(t) for t in frame.index]
    calm = (frame.speed < compass.CALM_MS).to_numpy()
    labels = [compass.label(d, lang) for d in frame.direction]
    hint = [f" · {tr('calm_short', lang)}" if c else '' for c in calm]
    fig = go.Figure()
    fig.add_scatter(x=x, y=frame.speed, mode='lines', connectgaps=False, name=tr('speed', lang), yaxis='y',
                    line=dict(color=ui.C['accent2'], width=2.2),
                    hovertemplate=f"%{{y:.1f}} {tr('ms', lang)}<extra></extra>")
    fig.add_scatter(x=x, y=frame.direction, mode='markers', name=tr('direction_short', lang), yaxis='y2',
                    customdata=np.array(list(zip(labels, hint, strict=True)), dtype=object),
                    marker=dict(size=9, symbol=['circle-open' if c else 'circle' for c in calm],
                                color=[ui.C['muted'] if c else ui.C['text'] for c in calm],
                                line=dict(width=1.5, color=ui.C['muted'])),
                    hovertemplate='%{customdata[0]}%{customdata[1]}<extra></extra>')
    ui.style(fig, 470)
    axis = compass.AXIS.get(lang, compass.AXIS['en'])
    grid = dict(gridcolor=ui.C['grid'], zeroline=False)
    fig.update_layout(
        showlegend=False, hovermode='x unified', hoversubplots='axis', margin=dict(l=8, r=8, t=30, b=8),
        hoverlabel=dict(bgcolor=ui.C['panel2'], bordercolor=ui.C['border'], font=dict(color=ui.C['text'], size=12)),
        yaxis=dict(domain=[0.5, 1], rangemode='tozero', title='', **grid),
        yaxis2=dict(domain=[0, 0.36], range=[-20, 380], tickvals=list(axis), ticktext=[f'{d}°' for d in axis],
                    title='', anchor='x', **grid),
        xaxis=dict(type='date', anchor='y2', hoverformat='%d.%m.%Y %H:%M', tickangle=0, tickfont=dict(size=11),
                   minor=dict(dtick=6 * 3600 * 1000, showgrid=True, gridcolor='rgba(26,44,63,0.45)'), **grid),
    )
    # Compass names inside the direction panel (right edge) keep the y labels narrow on phones.
    for deg, name in axis.items():
        fig.add_annotation(text=name, x=1, y=deg, xref='paper', yref='y2', xanchor='right', yanchor='middle',
                           showarrow=False, font=dict(size=10, color=ui.C['muted']), bgcolor='rgba(7,17,28,0.7)')
    titles = (tr('speed', lang) + (f" · {height_m} {tr('m_unit', lang)}" if height_m else ''), tr('direction_short', lang))
    for y, text in zip((1.0, 0.36), titles, strict=True):
        fig.add_annotation(text=text, x=0, y=y, xref='paper', yref='paper', xanchor='left', yanchor='bottom',
                           showarrow=False, yshift=4, font=dict(size=13, color=ui.C['muted']))
    if len(frame.index):
        vals, text = time_ticks(frame.index.min(), frame.index.max())
        fig.update_xaxes(tickvals=vals, ticktext=text)
    return fig
