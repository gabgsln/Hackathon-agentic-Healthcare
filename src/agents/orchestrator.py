"""Main orchestrator agent — drives the Claude tool-use loop to generate medical reports.

Imaging-first architecture:
  1. vision_tool (deterministic, DICOM-based) is run FIRST — before any LLM call.
     If it cannot produce measurements, the pipeline hard-fails immediately.
  2. The LLM receives the pre-computed vision measurements as context and uses
     report_tool + timeline_tool to assemble the final structured report.
  3. Excel data is used ONLY for patient/study metadata — never as a lesion source.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
from loguru import logger

from src.agents.tools.report_tool import TOOL_DEFINITION as REPORT_TOOL_DEF
from src.agents.tools.report_tool import run_report_tool
from src.agents.tools.timeline_tool import TOOL_DEFINITION as TIMELINE_TOOL_DEF
from src.agents.tools.timeline_tool import run_timeline_tool
from src.agents.tools.viz_tool import TOOL_DEFINITION as VIZ_TOOL_DEF
from src.agents.tools.viz_tool import run_viz_tool
from src.core.config import settings
from src.core.types import (
    GeneratedReport,
    PatientTimeline,
    ReportRequest,
    ReportSections,
)
from src.pipelines.compute_analysis import compute_analysis_from_vision
from src.tools.vision_tool import run_vision_tool

# LLM tools available AFTER vision data is pre-loaded (no vision_tool in LLM loop)
TOOLS = [TIMELINE_TOOL_DEF, REPORT_TOOL_DEF, VIZ_TOOL_DEF]

SYSTEM_PROMPT = """You are an expert radiologist assistant generating structured thoracic CT reports.

## DATA GUARANTEE
Imaging measurements have ALREADY been computed deterministically from DICOM files
before this conversation started. The vision_output block in the user message contains
exact mm measurements (px → mm via PixelSpacing). You MUST use these measurements.
Do NOT invent, estimate, or approximate lesion sizes — use only the provided data.

## Available tools
- **timeline_tool**: Retrieve chronological patient metadata (dates, accession numbers).
  Use this if a patient timeline was provided alongside the images.
- **report_tool**: Assemble the final structured report. ALWAYS call this last.
- **viz_tool**: (optional) Generate charts from timeline data.

## Workflow
1. If a patient timeline is available, call `timeline_tool` for context.
2. Call `report_tool` to produce the final structured report sections.
   Populate every section using the vision_output data provided.
3. Optionally call `viz_tool` for supporting charts.

## Report standards
- French radiological terminology.
- Measurements in mm — cite only values from vision_output.
- Compare baseline vs. last exam when ≥2 studies are available.
- Flag urgent findings with "URGENT:" prefix.
- Mark uncertain findings with "à confirmer" or "possible".
- Always call `report_tool` as the FINAL step.
"""


def _format_vision_context(vision_output: dict[str, Any]) -> str:
    """Render vision_output as a readable text block for the LLM prompt."""
    lines = ["## Vision measurements (imaging-derived, DICOM-based)\n"]

    calibration = vision_output.get("calibration", {})
    ps = calibration.get("pixel_spacing_mm")
    lines.append(
        f"Calibration method: {calibration.get('method', 'N/A')}  "
        f"| PixelSpacing: {ps} mm"
    )

    warnings = vision_output.get("warnings", [])
    if warnings:
        lines.append("\nWarnings:")
        for w in warnings:
            lines.append(f"  - {w}")

    studies = vision_output.get("studies", [])
    for i, study in enumerate(studies):
        lines.append(
            f"\n### Study {i + 1}  "
            f"date={study.get('study_date', 'N/A')}  "
            f"patient={study.get('patient_id', 'N/A')}"
        )
        kpis = study.get("kpis", {})
        lines.append(
            f"  KPIs: sum_long_axis={kpis.get('sum_long_axis_mm')} mm  "
            f"dominant={kpis.get('dominant_lesion_mm')} mm  "
            f"n_lesions={kpis.get('lesion_count')}"
        )
        for lesion in study.get("lesions", []):
            lines.append(
                f"  Lesion {lesion.get('lesion_id', '?')}: "
                f"long={lesion.get('long_axis_mm')} mm  "
                f"short={lesion.get('short_axis_mm')} mm  "
                f"slice={lesion.get('slice_instance')}"
            )

    return "\n".join(lines)


class Orchestrator:
    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def run(
        self,
        request: ReportRequest,
        timeline: PatientTimeline | None,
        dicom_paths: list[Path],
        annotations_json: str | None = None,
    ) -> GeneratedReport:
        """Run the full imaging-first pipeline.

        Args:
            request:          Report request (patient_id, output_format, …).
            timeline:         Optional patient timeline (metadata only from Excel).
            dicom_paths:      Local DICOM file paths — MANDATORY.
            annotations_json: Lesion annotations JSON string (pixel coords).

        Raises:
            ValueError: If vision_tool cannot derive measurements.
        """
        logger.info(f"Orchestrator start — patient {request.patient_id}")

        # ── Step 1: Deterministic DICOM vision (MANDATORY, runs before LLM) ──
        logger.info(f"Running vision_tool on {len(dicom_paths)} DICOM path(s)")
        try:
            vision_output = run_vision_tool(
                dicom_paths=dicom_paths,
                annotations_json_str=annotations_json,
            )
        except ValueError as exc:
            # Hard-fail: re-raise with structured error intact
            logger.error(f"vision_tool hard-failed: {exc}")
            raise

        logger.info(
            f"vision_tool OK — {len(vision_output.get('studies', []))} study/ies, "
            f"{sum(len(s.get('lesions', [])) for s in vision_output.get('studies', []))} "
            f"lesion(s)"
        )

        # ── Step 2: Compute deterministic analysis from vision output ─────────
        if hasattr(timeline, "entries") and timeline is not None:
            # Build minimal timeline list for compute_analysis_from_vision
            [
                {
                    "study_date":      (e.date.isoformat() if hasattr(e, "date") and e.date else None),
                    "lesion_sizes_mm": [],  # sizes come from vision, not Excel
                    "report_sections": {},
                }
                for e in (timeline.entries or [])
            ]

        analysis = compute_analysis_from_vision(
            vision_output=vision_output,
            case_id=request.patient_id,
        )

        # ── Step 3: Build LLM user message with pre-computed vision context ───
        vision_ctx = _format_vision_context(vision_output)

        context_parts = [
            f"## Report Request\n"
            f"- Patient ID: {request.patient_id}\n"
            f"- Exam date: {request.exam_date or date.today()}\n"
            f"- Referring physician: {request.referring_physician or 'not specified'}\n"
            f"- DICOM files processed: {len(dicom_paths)}\n"
            f"- Timeline available: {'yes' if timeline else 'no'}\n",
            vision_ctx,
            f"\n## Deterministic analysis summary\n"
            f"- Overall status: **{analysis.get('overall_status', 'unknown').upper()}**\n"
            f"- Rule applied: {analysis.get('evidence', {}).get('rule_applied', 'N/A')}\n"
            f"- Baseline date: {analysis.get('baseline_study', {}).get('study_date', 'N/A')}\n"
            f"- Last exam date: {analysis.get('last_study', {}).get('study_date', 'N/A')}\n"
            f"- Delta lesions: {json.dumps(analysis.get('lesion_deltas', []), ensure_ascii=False)}\n",
        ]

        if timeline:
            context_parts.append(
                f"\n## Patient Info (from Excel — metadata only)\n"
                f"- Age: {timeline.patient.age}\n"
                f"- Sex: {timeline.patient.sex.value}\n"
                f"- Main diagnosis: {timeline.patient.main_diagnosis or 'not specified'}\n"
            )

        context_parts.append(
            "\nBased on the imaging measurements above, please generate the complete "
            "medical report using report_tool."
        )

        user_message = "\n".join(context_parts)
        messages: list[dict] = [{"role": "user", "content": user_message}]

        # ── Step 4: LLM agentic loop ──────────────────────────────────────────
        report_sections: ReportSections | None = None
        timeline_summary = ""
        total_tokens = 0
        max_iterations = 10

        for iteration in range(max_iterations):
            logger.debug(f"Agent iteration {iteration + 1}")

            response = await self.client.messages.create(
                model=settings.agent_model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            total_tokens += response.usage.input_tokens + response.usage.output_tokens
            logger.debug(
                f"stop_reason={response.stop_reason}, "
                f"blocks={len(response.content)}"
            )

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason != "tool_use":
                logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                logger.info(f"Tool call: {tool_name}({list(tool_input.keys())})")

                try:
                    if tool_name == "timeline_tool":
                        if timeline is None:
                            result_content = "No timeline data available."
                        else:
                            result_content = run_timeline_tool(
                                timeline=timeline,
                                focus_metrics=tool_input.get("focus_metrics"),
                                comparison_period=tool_input.get("comparison_period", "all"),
                            )
                            timeline_summary = result_content

                    elif tool_name == "report_tool":
                        report_sections = run_report_tool(**tool_input)
                        result_content = "Report sections assembled successfully."

                    elif tool_name == "viz_tool":
                        if timeline:
                            result_content = run_viz_tool(
                                timeline=timeline,
                                chart_type=tool_input.get("chart_type", "timeline_overview"),
                                output_path=tool_input.get("output_path"),
                            )
                        else:
                            result_content = "No timeline data for visualization."

                    else:
                        result_content = f"Unknown tool: {tool_name}"

                except Exception as e:
                    logger.error(f"Tool {tool_name} failed: {e}")
                    result_content = f"Tool error: {e}"

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     str(result_content),
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        if report_sections is None:
            logger.warning("Agent finished without calling report_tool — using empty sections")
            report_sections = ReportSections()

        logger.info(f"Orchestrator done — tokens used: {total_tokens}")
        return GeneratedReport(
            patient_id=request.patient_id,
            sections=report_sections,
            timeline_summary=timeline_summary,
            image_findings=[_format_vision_context(vision_output)],
            pipeline_version=settings.pipeline_version,
            tokens_used=total_tokens,
        )
