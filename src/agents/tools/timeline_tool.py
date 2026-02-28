"""Timeline tool: summarize patient evolution and trends from structured data."""

from loguru import logger

from src.core.types import PatientTimeline

TOOL_DEFINITION = {
    "name": "timeline_tool",
    "description": (
        "Analyze the patient's chronological data (lab results, exam measurements, nodule sizes) "
        "and return a structured summary of trends, evolutions, and clinically significant changes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "focus_metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Specific metrics to focus on, e.g. ['nodule_size', 'suv_max', 'CEA']. "
                    "If empty, analyze all available data."
                ),
            },
            "comparison_period": {
                "type": "string",
                "description": "Time period for comparison, e.g. '6 months', '1 year', 'all'",
            },
        },
        "required": [],
    },
}


def run_timeline_tool(
    timeline: PatientTimeline,
    focus_metrics: list[str] | None = None,
    comparison_period: str = "all",
) -> str:
    """Analyze the patient timeline and return a formatted trend summary."""
    logger.info(f"Running timeline analysis for patient {timeline.patient.patient_id}")

    sections = []

    # Patient summary
    p = timeline.patient
    sections.append(
        f"## Patient Summary\n"
        f"- ID: {p.patient_id}\n"
        f"- Age: {p.age} ans, Sex: {p.sex.value}\n"
        f"- Smoking: {p.smoking_status.value if p.smoking_status else 'unknown'}\n"
        f"- Main diagnosis: {p.main_diagnosis or 'not specified'}"
    )

    # Timeline entries
    if timeline.entries:
        sections.append("## Chronological Data")
        for entry in timeline.entries:
            line = f"- [{entry.date}] {entry.exam_type.value}: {entry.result}"
            if entry.unit:
                line += f" {entry.unit}"
            if entry.reference_range:
                line += f" (ref: {entry.reference_range})"
            if entry.notes:
                line += f" — {entry.notes}"
            sections.append(line)

    # Nodule evolution
    if timeline.nodules:
        sections.append("## Nodule Evolution")
        nodule_ids = sorted({n.nodule_id for n in timeline.nodules})
        for nid in nodule_ids:
            measurements = sorted(
                [n for n in timeline.nodules if n.nodule_id == nid],
                key=lambda n: n.date,
            )
            sections.append(f"\n### Nodule {nid}")
            if measurements[0].location:
                sections.append(f"Location: {measurements[0].location}")

            for m in measurements:
                line = f"- [{m.date}] {m.size_mm} mm"
                if m.density:
                    line += f", density: {m.density}"
                if m.suv_max is not None:
                    line += f", SUV max: {m.suv_max}"
                sections.append(line)

            # Compute growth
            if len(measurements) >= 2:
                first, last = measurements[0], measurements[-1]
                delta = last.size_mm - first.size_mm
                pct = (delta / first.size_mm * 100) if first.size_mm > 0 else 0
                trend = "stable" if abs(pct) < 5 else ("progression" if delta > 0 else "regression")
                sections.append(
                    f"**Trend**: {trend} ({delta:+.1f} mm / {pct:+.1f}% "
                    f"over {(last.date - first.date).days} days)"
                )

    result = "\n".join(sections)
    logger.debug(f"Timeline summary: {len(result)} chars")
    return result
