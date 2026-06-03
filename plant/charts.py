"""
Plotly figures for the schedule board (M7) — Gantt + utilization.

Figures are built server-side from a persisted Schedule and rendered as HTML divs
into the templates (Plotly.js comes from the CDN). The palette matches the dark
control-room theme: mint for normal lots, amber for AOG hot lots.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from plant.model.models import Schedule

# Theme tokens (kept in sync with the CSS variables in base.html).
_INK = "#0e1513"
_GRID = "rgba(120,160,150,0.14)"
_TEXT = "#cfe0d8"
_MUTED = "#7d908a"
_AMBER = "#f2a341"  # AOG / hot
_MINT = "#46c8a0"  # normal / feasible
_RED = "#e5584d"  # late

_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Mono, monospace", color=_TEXT, size=12),
    margin=dict(l=10, r=16, t=10, b=10),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=_MUTED)),
    xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID, linecolor=_GRID),
    yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID, linecolor=_GRID),
)

_CONFIG = {"displayModeBar": False, "responsive": True}


def _rows(schedule: Schedule) -> pd.DataFrame:
    origin = schedule.horizon_start
    data = []
    for so in schedule.scheduled_ops.select_related(
        "operation", "resource", "job__routing", "worker"
    ):
        data.append(
            {
                "resource": so.resource.name,
                "job": f"#{so.job_id} {so.job.routing.part_name}",
                "operation": so.operation.name,
                "worker": so.worker.name if so.worker else "—",
                "start": origin + timedelta(minutes=so.start_minute),
                "finish": origin + timedelta(minutes=so.end_minute),
                "lot": "AOG" if so.job.is_aog else "normal",
            }
        )
    return pd.DataFrame(data)


def _empty(message: str) -> str:
    fig = go.Figure()
    fig.update_layout(**_LAYOUT, height=140)
    fig.add_annotation(text=message, showarrow=False, font=dict(color=_MUTED, size=13))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig.to_html(full_html=False, include_plotlyjs=False, config=_CONFIG)


def gantt_html(schedule: Schedule | None, *, by: str = "resource") -> str:
    """A Gantt of the schedule, laned by resource (default) or by job."""
    if schedule is None or not schedule.scheduled_ops.exists():
        return _empty("No schedule yet — run the solver.")

    df = _rows(schedule)
    lane = "resource" if by == "resource" else "job"
    df = df.sort_values(lane, ascending=False)
    fig = px.timeline(
        df,
        x_start="start",
        x_end="finish",
        y=lane,
        color="lot",
        color_discrete_map={"normal": _MINT, "AOG": _AMBER},
        hover_data=["job", "operation", "worker"],
    )
    fig.update_layout(**_LAYOUT, height=max(220, 34 * df[lane].nunique() + 60), bargap=0.35)
    fig.update_traces(marker_line_color=_INK, marker_line_width=1)
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)
    return fig.to_html(full_html=False, include_plotlyjs=False, config=_CONFIG)


def utilization_html(schedule: Schedule | None) -> str:
    """Per-resource utilization (busy ÷ capacity·horizon), bottleneck on top."""
    if schedule is None or not schedule.scheduled_ops.exists():
        return _empty("")

    ops = list(schedule.scheduled_ops.select_related("resource"))
    span = max((o.end_minute for o in ops), default=0) or 1
    busy: dict[str, int] = {}
    cap: dict[str, int] = {}
    for o in ops:
        busy[o.resource.name] = busy.get(o.resource.name, 0) + (o.end_minute - o.start_minute)
        cap[o.resource.name] = o.resource.capacity
    rows = sorted(
        ({"resource": r, "util": 100 * busy[r] / (cap[r] * span)} for r in busy),
        key=lambda d: d["util"],
    )
    df = pd.DataFrame(rows)
    fig = px.bar(df, x="util", y="resource", orientation="h", text="util")
    fig.update_traces(
        marker_color=_MINT,
        marker_line_color=_INK,
        marker_line_width=1,
        texttemplate="%{text:.0f}%",
        textposition="outside",
        textfont=dict(color=_MUTED),
    )
    fig.update_layout(**_LAYOUT, height=max(160, 30 * len(df) + 50))
    fig.update_xaxes(title=None, ticksuffix="%", range=[0, max(df["util"].max() * 1.25, 10)])
    fig.update_yaxes(title=None)
    return fig.to_html(full_html=False, include_plotlyjs=False, config=_CONFIG)
