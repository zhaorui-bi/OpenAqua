"""Horizontal flowchart visualisation for a treatment unit chain."""
from __future__ import annotations

import plotly.graph_objects as go

_BOX_W = 1.6
_BOX_H = 0.7
_GAP = 0.55
_COLOR_BOX = "#2563EB"
_COLOR_BORDER = "#1E40AF"
_COLOR_ARROW = "#9CA3AF"


def render_chain(chain: list[str]) -> go.Figure:
    """Return a Plotly figure showing the treatment chain as horizontal boxes."""
    n = len(chain)
    fig = go.Figure()
    step = _BOX_W + _GAP
    total_w = n * step - _GAP

    for i, unit in enumerate(chain):
        x0 = i * step
        x1 = x0 + _BOX_W
        xc = (x0 + x1) / 2

        # Box shape
        fig.add_shape(
            type="rect",
            x0=x0, x1=x1, y0=0, y1=_BOX_H,
            fillcolor=_COLOR_BOX,
            line=dict(color=_COLOR_BORDER, width=1.5),
        )
        # Wrap long unit names so they fit inside the box
        label = unit if len(unit) <= 18 else unit.replace(" and ", "\n& ").replace(" ", "\n", 1)
        fig.add_annotation(
            x=xc, y=_BOX_H / 2,
            text=label,
            showarrow=False,
            font=dict(color="white", size=10, family="Arial"),
            align="center",
        )
        # Arrow between boxes
        if i < n - 1:
            fig.add_annotation(
                x=x1 + _GAP / 2, y=_BOX_H / 2,
                text="→",
                showarrow=False,
                font=dict(size=18, color=_COLOR_ARROW),
            )

    fig.update_layout(
        xaxis=dict(visible=False, range=[-0.1, total_w + 0.1]),
        yaxis=dict(visible=False, range=[-0.2, _BOX_H + 0.2]),
        height=115,
        margin=dict(l=5, r=5, t=5, b=5),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
