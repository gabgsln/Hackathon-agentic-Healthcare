"""LLM enrichment step: fill narrative report sections from DICOM analysis.

Uses claude-haiku-4-5 with forced tool_use (structured output) so the response
is guaranteed to match the expected schema.

Only fills narrative/qualitative fields:
  - latest_study_technique   → acquisition description
  - latest_report            → preliminary findings (conservative, data-grounded)
  - latest_conclusions       → brief clinical impression

Never modifies deterministic fields:
  - overall_status, kpi, dicom (pixel stats, metadata)

Gracefully returns the analysis unchanged if:
  - ANTHROPIC_API_KEY is absent
  - anthropic package is not installed
  - The API call fails for any reason

Usage:
    from src.pipelines.llm_enrichment import enrich_analysis
    analysis = enrich_analysis(analysis)          # no-op if no API key
    analysis = enrich_analysis(analysis, dry_run=True)  # skip API call, return as-is
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Tool definition (forced structured output) ────────────────────────────────

_ENRICH_TOOL: dict[str, Any] = {
    "name": "write_report_sections",
    "description": (
        "Write three concise technical report sections in French, "
        "based exclusively on the provided DICOM metadata and image statistics. "
        "Do NOT invent clinical findings not supported by the data."
    ),
    "input_schema": {
        "type": "object",
        "required": ["study_technique", "preliminary_findings", "conclusions"],
        "additionalProperties": False,
        "properties": {
            "study_technique": {
                "type": "string",
                "description": (
                    "Technical acquisition description: modality, body part, "
                    "slice thickness, pixel spacing, date. 2–4 sentences max."
                ),
            },
            "preliminary_findings": {
                "type": "string",
                "description": (
                    "Objective observations derivable from pixel statistics "
                    "(HU range, image dimensions, data quality). "
                    "State clearly that morphological interpretation requires radiologist review. "
                    "3–5 sentences max."
                ),
            },
            "conclusions": {
                "type": "string",
                "description": (
                    "One-paragraph technical summary of image quality and "
                    "acquisition adequacy. Do not make clinical diagnoses. "
                    "2–3 sentences max."
                ),
            },
        },
    },
}

_SYSTEM_PROMPT = (
    "Tu es un assistant en radiologie. "
    "À partir des métadonnées DICOM et des statistiques pixel fournies, "
    "génère uniquement du contenu technique factuel en français. "
    "Tu ne peux PAS poser de diagnostic clinique à partir de statistiques pixel seules. "
    "Sois précis, concis et conservateur."
)

# ── Immutable fields — never touched by enrichment ────────────────────────────

_PROTECTED_KEYS = frozenset({
    "case_id", "patient_id", "overall_status",
    "evidence", "lesion_deltas", "kpi", "dicom",
})


# ── Main public function ───────────────────────────────────────────────────────

def enrich_analysis(
    analysis: dict[str, Any],
    *,
    api_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add LLM-generated narrative sections to the analysis dict.

    Args:
        analysis:  The validated analysis dict from ``analyze_dicom()``.
        api_key:   Override ANTHROPIC_API_KEY (useful for tests).
        dry_run:   Skip the API call entirely and return *analysis* unchanged.

    Returns:
        The analysis dict, possibly enriched with:
        - ``latest_study_technique``
        - ``latest_report``
        - ``latest_conclusions``
        - ``llm_enriched: True``

        All protected/deterministic fields are unchanged.
        On any failure the original *analysis* is returned unchanged.
    """
    if dry_run:
        return analysis

    # Resolve API key
    key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        logger.debug("[llm_enrichment] ANTHROPIC_API_KEY not set — skipping enrichment")
        return analysis

    try:
        import anthropic  # late import: optional dependency for enrichment
    except ImportError:
        logger.warning("[llm_enrichment] anthropic package not installed — skipping enrichment")
        return analysis

    meta  = (analysis.get("dicom") or {}).get("metadata", {})
    stats = (analysis.get("dicom") or {}).get("image_stats", {})

    context_payload = {
        "modality":               meta.get("Modality"),
        "body_part":              meta.get("BodyPartExamined"),
        "study_date":             meta.get("StudyDate"),
        "series_description":     meta.get("SeriesDescription"),
        "slice_thickness_mm":     meta.get("SliceThickness"),
        "pixel_spacing_mm":       meta.get("PixelSpacing"),
        "image_shape_px":         stats.get("shape"),
        "hu_min":                 stats.get("min"),
        "hu_max":                 stats.get("max"),
        "hu_mean":                stats.get("mean"),
        "hu_std":                 stats.get("std"),
        "data_consistency_score": stats.get("data_consistency_score"),
    }

    user_msg = (
        "Données DICOM disponibles :\n"
        f"{json.dumps(context_payload, ensure_ascii=False, indent=2)}\n\n"
        "Génère les trois sections techniques du compte rendu en français."
    )

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            tools=[_ENRICH_TOOL],
            tool_choice={"type": "tool", "name": "write_report_sections"},
        )
    except Exception as exc:
        logger.warning(f"[llm_enrichment] API call failed ({exc}) — skipping enrichment")
        return analysis

    # Extract the guaranteed tool_use block
    enriched_fields: dict[str, str] = {}
    for block in response.content:
        if block.type == "tool_use" and block.name == "write_report_sections":
            enriched_fields = block.input
            break

    if not enriched_fields:
        logger.warning("[llm_enrichment] No tool_use block in response — skipping enrichment")
        return analysis

    # Merge: only add narrative keys, never overwrite protected ones
    additions: dict[str, Any] = {
        "latest_study_technique": enriched_fields.get("study_technique"),
        "latest_report":          enriched_fields.get("preliminary_findings"),
        "latest_conclusions":     enriched_fields.get("conclusions"),
        "llm_enriched":           True,
    }

    # Safety guard — should never trigger given _PROTECTED_KEYS, but belt-and-suspenders
    for key_name in _PROTECTED_KEYS:
        additions.pop(key_name, None)

    logger.info("[llm_enrichment] Analysis enriched with LLM narrative sections")
    return {**analysis, **additions}
