"""Decomposed score bar chart for a recommendation."""
from __future__ import annotations

import plotly.graph_objects as go

_SCORE_ITEMS = [
    ("Coverage",    "coverage_score",    "#10B981"),
    ("Constraint",  "constraint_score",  "#3B82F6"),
    ("Evidence",    "evidence_score",    "#8B5CF6"),
    ("Risk Penalty","risk_penalty",      "#EF4444"),
]


def render_score_chart(rank_score: dict) -> go.Figure:
    """Return a horizontal bar chart of decomposed scores (risk shown as negative)."""
    labels, values, colors = [], [], []
    for label, key, color in _SCORE_ITEMS:
        v = rank_score.get(key, 0.0)
        if key == "risk_penalty":
            v = -abs(v)   # display penalty as leftward bar
        labels.append(label)
        values.append(v)
        colors.append(color)

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker_color=colors,
        text=[f"{v:+.2f}" for v in values],
        textposition="outside",
        cliponaxis=False,
    ))
    fig.update_layout(
        xaxis=dict(range=[-1.3, 1.3], zeroline=True, zerolinecolor="#D1D5DB", zerolinewidth=1),
        yaxis=dict(autorange="reversed"),
        height=185,
        margin=dict(l=10, r=55, t=8, b=8),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
