"""Viz tool: generate Plotly charts from patient timeline data."""
from pathlib import Path

import plotly.graph_objects as go
from loguru import logger

from src.core.types import PatientTimeline

TOOL_DEFINITION = {
    "name": "viz_tool",
    "description": (
        "Generate charts and visualizations from patient timeline data. "
        "Returns a path to the generated HTML chart file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": ["nodule_growth", "timeline_overview", "lab_trends"],
                "description": "Type of chart to generate",
            },
            "output_path": {
                "type": "string",
                "description": "Path to save the HTML chart",
            },
        },
        "required": ["chart_type"],
    },
}


def _nodule_growth_chart(timeline: PatientTimeline) -> go.Figure:
    fig = go.Figure()
    nodule_ids = sorted({n.nodule_id for n in timeline.nodules})
    for nid in nodule_ids:
        measurements = sorted(
            [n for n in timeline.nodules if n.nodule_id == nid],
            key=lambda n: n.date,
        )
        fig.add_trace(go.Scatter(
            x=[str(m.date) for m in measurements],
            y=[m.size_mm for m in measurements],
            mode="lines+markers",
            name=f"Nodule {nid}",
            hovertemplate="%{x}: %{y} mm<extra></extra>",
        ))
    fig.update_layout(
        title="Nodule Size Evolution",
        xaxis_title="Date",
        yaxis_title="Size (mm)",
        template="plotly_white",
        legend_title="Nodule",
    )
    return fig


def _timeline_overview_chart(timeline: PatientTimeline) -> go.Figure:
    entries = timeline.entries
    if not entries:
        return go.Figure()

    exam_types = sorted({e.exam_type.value for e in entries})
    colors = {"CT": "#1f77b4", "PET": "#ff7f0e", "BIO": "#2ca02c", "RX": "#9467bd", "OTHER": "#7f7f7f"}

    fig = go.Figure()
    for et in exam_types:
        subset = [e for e in entries if e.exam_type.value == et]
        fig.add_trace(go.Scatter(
            x=[str(e.date) for e in subset],
            y=[et] * len(subset),
            mode="markers",
            name=et,
            marker=dict(size=12, color=colors.get(et, "#333")),
            hovertemplate="%{x}: " + et + "<extra></extra>",
        ))

    fig.update_layout(
        title="Patient Exam Timeline",
        xaxis_title="Date",
        yaxis_title="Exam Type",
        template="plotly_white",
    )
    return fig


def run_viz_tool(
    timeline: PatientTimeline,
    chart_type: str,
    output_path: str | None = None,
) -> str:
    """Generate a chart and save it to HTML. Returns the output path."""
    logger.info(f"Generating chart: {chart_type}")

    if chart_type == "nodule_growth":
        fig = _nodule_growth_chart(timeline)
    elif chart_type == "timeline_overview":
        fig = _timeline_overview_chart(timeline)
    else:
        fig = _timeline_overview_chart(timeline)

    if output_path is None:
        output_path = f"/tmp/{chart_type}_{timeline.patient.patient_id}.html"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(output_path)
    logger.info(f"Chart saved: {output_path}")
    return output_path
