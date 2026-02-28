"""Main orchestrator agent — drives the Claude tool-use loop to generate medical reports."""
import json
from datetime import date

import anthropic
from loguru import logger

from src.agents.tools.report_tool import TOOL_DEFINITION as REPORT_TOOL_DEF
from src.agents.tools.report_tool import run_report_tool
from src.agents.tools.timeline_tool import TOOL_DEFINITION as TIMELINE_TOOL_DEF
from src.agents.tools.timeline_tool import run_timeline_tool
from src.agents.tools.vision_tool import TOOL_DEFINITION as VISION_TOOL_DEF
from src.agents.tools.vision_tool import run_vision_tool
from src.agents.tools.viz_tool import TOOL_DEFINITION as VIZ_TOOL_DEF
from src.agents.tools.viz_tool import run_viz_tool
from src.core.config import settings
from src.core.types import (
    GeneratedReport,
    ImageMetadata,
    PatientTimeline,
    ReportRequest,
    ReportSections,
)

TOOLS = [TIMELINE_TOOL_DEF, VISION_TOOL_DEF, REPORT_TOOL_DEF, VIZ_TOOL_DEF]

SYSTEM_PROMPT = """You are an expert radiologist assistant. Your task is to generate a complete,
structured thoracic CT scan report based on the patient data provided.

You have access to the following tools:
- **timeline_tool**: Analyze chronological patient data (lab results, nodule measurements)
- **vision_tool**: Analyze medical images using computer vision
- **report_tool**: Assemble the final structured report sections
- **viz_tool**: (optional) Generate charts for visualization

## Workflow
1. First, call `timeline_tool` to understand the patient's clinical evolution
2. If images are available, call `vision_tool` to analyze them
3. Finally, call `report_tool` to assemble the complete report with all sections filled
4. Optionally call `viz_tool` to generate supporting charts

## Report Standards
- Use standard radiological French terminology
- Be precise with measurements (in mm)
- Note comparisons with previous exams when data is available
- Provide actionable recommendations
- Flag urgent findings with "URGENT:" prefix

## Important
- Always call `report_tool` as the final step to produce the structured output
- Base conclusions strictly on provided data — do not hallucinate findings
- Mark any uncertain findings with appropriate qualification (e.g., "possible", "à confirmer")
"""


class Orchestrator:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def run(
        self,
        request: ReportRequest,
        timeline: PatientTimeline | None,
        images: list[ImageMetadata],
    ) -> GeneratedReport:
        logger.info(f"Starting orchestrator for patient {request.patient_id}")

        # Build initial user message
        context_parts = [
            f"## Report Request\n"
            f"- Patient ID: {request.patient_id}\n"
            f"- Exam date: {request.exam_date or date.today()}\n"
            f"- Referring physician: {request.referring_physician or 'not specified'}\n"
            f"- Images available: {len(images)}\n"
            f"- Timeline available: {'yes' if timeline else 'no'}\n"
        ]

        if timeline:
            context_parts.append(
                f"\n## Patient Info\n"
                f"- Age: {timeline.patient.age} ans\n"
                f"- Sex: {timeline.patient.sex.value}\n"
                f"- Main diagnosis: {timeline.patient.main_diagnosis or 'not specified'}\n"
                f"- Smoking: {timeline.patient.smoking_status.value if timeline.patient.smoking_status else 'unknown'}\n"
                f"- Timeline entries: {len(timeline.entries)}\n"
                f"- Nodule measurements: {len(timeline.nodules)}\n"
            )

        if images:
            context_parts.append(
                f"\n## Available Images ({len(images)})\n"
                + "\n".join(
                    f"- [{i}] {img.filename}"
                    + (f" (date: {img.exam_date})" if img.exam_date else "")
                    + (f", {img.modality}" if img.modality else "")
                    for i, img in enumerate(images)
                )
            )

        user_message = "\n".join(context_parts) + "\n\nPlease generate the complete medical report."

        messages: list[dict] = [{"role": "user", "content": user_message}]

        # Agentic loop
        report_sections: ReportSections | None = None
        timeline_summary = ""
        image_findings: list[str] = []
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
                f"Response: stop_reason={response.stop_reason}, "
                f"content_blocks={len(response.content)}"
            )

            # Check if done
            if response.stop_reason == "end_turn":
                logger.info("Agent finished (end_turn)")
                break

            if response.stop_reason != "tool_use":
                logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                break

            # Process tool calls
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

                    elif tool_name == "vision_tool":
                        if not images:
                            result_content = "No images available."
                        else:
                            result_content = await run_vision_tool(
                                image_indices=tool_input.get("image_indices", [0]),
                                images=images,
                                focus=tool_input.get("focus"),
                            )
                            image_findings.append(result_content)

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
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result_content),
                })

            # Append assistant turn + tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            # If report was assembled, we can stop
            if report_sections is not None and all(
                b.type != "tool_use" or b.name != "report_tool"
                for b in response.content
            ):
                # Check next response won't have more tool calls needed
                pass

        if report_sections is None:
            logger.warning("Agent finished without calling report_tool — using empty sections")
            report_sections = ReportSections()

        logger.info(f"Orchestrator done — tokens used: {total_tokens}")
        return GeneratedReport(
            patient_id=request.patient_id,
            sections=report_sections,
            timeline_summary=timeline_summary,
            image_findings=image_findings,
            pipeline_version=settings.pipeline_version,
            tokens_used=total_tokens,
        )
