"""Report tool: assemble and structure the final medical report sections."""
from loguru import logger

from src.core.types import ReportSections

TOOL_DEFINITION = {
    "name": "report_tool",
    "description": (
        "Assemble the final structured medical report. Call this tool once you have "
        "gathered all findings from vision and timeline analysis. Provide the content "
        "for each section of the radiology report."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "indication": {
                "type": "string",
                "description": "Clinical indication / reason for examination",
            },
            "technique": {
                "type": "string",
                "description": "Technical parameters of the exam",
            },
            "parenchyma": {
                "type": "string",
                "description": "Pulmonary parenchyma findings",
            },
            "mediastinum": {
                "type": "string",
                "description": "Mediastinum and vascular structures findings",
            },
            "pleura": {
                "type": "string",
                "description": "Pleural and thoracic wall findings",
            },
            "upper_abdomen": {
                "type": "string",
                "description": "Upper abdominal findings (if visible)",
            },
            "comparison": {
                "type": "string",
                "description": "Comparison with previous exams",
            },
            "conclusion": {
                "type": "string",
                "description": "Main conclusions and diagnosis",
            },
            "recommendations": {
                "type": "string",
                "description": "Clinical recommendations and follow-up",
            },
        },
        "required": ["conclusion", "recommendations"],
    },
}


def run_report_tool(**kwargs) -> ReportSections:
    """Build a ReportSections object from tool input."""
    logger.info("Assembling report sections")
    sections = ReportSections(
        indication=kwargs.get("indication", ""),
        technique=kwargs.get("technique", ""),
        parenchyma=kwargs.get("parenchyma", ""),
        mediastinum=kwargs.get("mediastinum", ""),
        pleura=kwargs.get("pleura", ""),
        upper_abdomen=kwargs.get("upper_abdomen", ""),
        comparison=kwargs.get("comparison", ""),
        conclusion=kwargs.get("conclusion", ""),
        recommendations=kwargs.get("recommendations", ""),
    )
    logger.debug(f"Report assembled: conclusion={sections.conclusion[:80]}...")
    return sections
