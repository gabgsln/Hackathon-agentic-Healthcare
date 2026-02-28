"""Clinical Validation Agent — lightweight LLM-based consistency checker.

Strategy
--------
Uses claude-haiku with forced ``tool_use`` (structured output) to add a
medical-consistency validation layer on top of the deterministic analysis.
The model reasons over structured JSON — it never sees raw pixel data and
never writes free-text reports.

What it validates
-----------------
- HU range plausibility for the stated modality
- Pixel spacing / slice thickness within clinically normal bounds
- Image dimensions large enough to be diagnostically useful
- Metadata completeness (required identifiers present)
- RECIST coherence (status vs. lesion_deltas agreement)
- Data consistency score quality gate

What it NEVER does
------------------
- Diagnose, treat, or prescribe
- Modify deterministic fields (overall_status, kpi, dicom, evidence)
- Write narrative report sections (that is llm_enrichment's job)

Output added to analysis dict
------------------------------
  "validation": {
      "confidence_score":            float  0.0 – 1.0
      "clinical_consistency_score":  float  0.0 – 1.0
      "anomaly_flags":               list[str]  snake_case codes
      "validation_notes":            str | null
      "validated_at":                str  ISO-8601
      "model_used":                  str
  }

Gracefully returns analysis unchanged if:
  - ANTHROPIC_API_KEY is absent
  - anthropic package is not installed
  - The API call fails for any reason
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Protected fields — never modified by validation ──────────────────────────

_PROTECTED_KEYS = frozenset({
    "pipeline_version", "case_id", "patient_id",
    "overall_status", "evidence", "lesion_deltas", "kpi", "dicom", "imaging",
    "status_reason", "status_explanation",
    # llm_enrichment fields
    "latest_study_technique", "latest_report", "latest_conclusions",
    "latest_clinical_information", "llm_enriched",
})

# ── Tool definition (forced structured output) ────────────────────────────────

_VALIDATION_TOOL: dict[str, Any] = {
    "name": "validate_clinical_data",
    "description": (
        "Perform a technical clinical-data consistency check on the DICOM analysis dict. "
        "Assess data quality, flag anomalies, and assign confidence scores. "
        "Base your assessment ONLY on the provided structured JSON — do NOT diagnose."
    ),
    "input_schema": {
        "type": "object",
        "required": ["confidence_score", "clinical_consistency_score", "anomaly_flags"],
        "additionalProperties": False,
        "properties": {
            "confidence_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Overall pipeline confidence: 1.0 = all data internally consistent "
                    "and within expected ranges; 0.0 = serious quality or coherence issues."
                ),
            },
            "clinical_consistency_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Medical consistency: do modality, HU range, pixel spacing, "
                    "image dimensions, and overall_status all agree? "
                    "1.0 = fully consistent; 0.0 = major inconsistencies detected."
                ),
            },
            "anomaly_flags": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
                "description": (
                    "Short snake_case codes for each detected anomaly or data quality issue. "
                    "Examples: hu_range_outside_ct_bounds, pixel_spacing_abnormally_large, "
                    "missing_patient_id, data_consistency_score_low, "
                    "recist_status_lesion_delta_mismatch."
                ),
            },
            "validation_notes": {
                "type": "string",
                "description": (
                    "One sentence max: the single most critical finding requiring attention. "
                    "Omit if no significant issues found."
                ),
            },
        },
    },
}

_SYSTEM_PROMPT = (
    "Tu es un agent de validation technique médicale. "
    "À partir des données JSON d'une analyse DICOM, tu dois:\n"
    "1. Vérifier la cohérence des données (plage HU vs modalité, dimensions, espacements)\n"
    "2. Détecter les anomalies de qualité (données manquantes, valeurs hors plage)\n"
    "3. Attribuer des scores de confiance basés UNIQUEMENT sur la cohérence des données\n"
    "4. NE JAMAIS poser de diagnostic clinique\n"
    "5. NE JAMAIS inventer de données absentes du JSON fourni\n\n"
    "Plages normales de référence pour CT:\n"
    "  HU min attendu: > -1100  |  HU max attendu: < 4000\n"
    "  PixelSpacing typique: 0.1–2.5 mm  |  SliceThickness typique: 0.5–10 mm\n"
    "  Dimensions minimales utiles: 64×64 px\n"
    "  data_consistency_score acceptable: ≥ 0.5"
)


# ── Context builder ───────────────────────────────────────────────────────────

def _build_validation_context(analysis: dict[str, Any]) -> dict[str, Any]:
    """Extract only the fields relevant for consistency checking."""
    meta  = (analysis.get("dicom") or {}).get("metadata", {})
    stats = (analysis.get("dicom") or {}).get("image_stats", {})
    img   = analysis.get("imaging", {})
    kpi   = analysis.get("kpi", {})

    return {
        # Identity
        "pipeline_version":    analysis.get("pipeline_version"),
        "overall_status":      analysis.get("overall_status"),
        "status_reason":       analysis.get("status_reason"),
        # DICOM metadata
        "modality":            meta.get("Modality"),
        "body_part":           meta.get("BodyPartExamined"),
        "study_date":          meta.get("StudyDate"),
        "patient_id_present":  bool(meta.get("PatientID")),
        "study_uid_present":   bool(meta.get("StudyInstanceUID")),
        "pixel_spacing_mm":    meta.get("PixelSpacing"),
        "slice_thickness_mm":  meta.get("SliceThickness"),
        # Image stats
        "hu_min":              stats.get("min"),
        "hu_max":              stats.get("max"),
        "hu_mean":             stats.get("mean"),
        "hu_std":              stats.get("std"),
        "image_shape":         stats.get("shape"),
        "data_consistency_score": stats.get("data_consistency_score"),
        # Imaging geometry
        "input_kind":          img.get("input_kind"),
        "n_slices":            img.get("n_slices"),
        "is_3d":               img.get("is_3d"),
        # RECIST coherence
        "lesion_count_current": kpi.get("lesion_count_current", 0),
        "lesion_deltas_count":  len(analysis.get("lesion_deltas", [])),
        "data_completeness":    kpi.get("data_completeness_score"),
    }


# ── Main public function ───────────────────────────────────────────────────────

def validate_clinical(
    analysis: dict[str, Any],
    *,
    api_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add LLM-driven clinical consistency validation to the analysis dict.

    Args:
        analysis: The enriched analysis dict (post-llm_enrichment).
        api_key:  Override ANTHROPIC_API_KEY (useful for tests).
        dry_run:  Skip API call and return *analysis* unchanged.

    Returns:
        The analysis dict, possibly with a ``validation`` block added:
        - ``confidence_score``            (0.0–1.0)
        - ``clinical_consistency_score``  (0.0–1.0)
        - ``anomaly_flags``               (list[str])
        - ``validation_notes``            (str | None)
        - ``validated_at``                (ISO-8601 UTC)
        - ``model_used``                  (str)

        On any failure the original *analysis* is returned unchanged.
    """
    if dry_run:
        return analysis

    key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        logger.debug("[clinical_validation] ANTHROPIC_API_KEY not set — skipping")
        return analysis

    try:
        import anthropic
    except ImportError:
        logger.warning("[clinical_validation] anthropic package not installed — skipping")
        return analysis

    ctx = _build_validation_context(analysis)
    user_msg = (
        "Données d'analyse DICOM à valider :\n"
        f"{json.dumps(ctx, ensure_ascii=False, indent=2)}\n\n"
        "Effectue la validation de cohérence clinique."
    )

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            tools=[_VALIDATION_TOOL],
            tool_choice={"type": "tool", "name": "validate_clinical_data"},
        )
    except Exception as exc:
        logger.warning(f"[clinical_validation] API call failed ({exc}) — skipping")
        return analysis

    # Extract guaranteed tool_use block
    tool_output: dict[str, Any] = {}
    for block in response.content:
        if block.type == "tool_use" and block.name == "validate_clinical_data":
            tool_output = block.input
            break

    if not tool_output:
        logger.warning("[clinical_validation] No tool_use block in response — skipping")
        return analysis

    validation_block: dict[str, Any] = {
        "confidence_score":           float(tool_output.get("confidence_score", 0.5)),
        "clinical_consistency_score": float(tool_output.get("clinical_consistency_score", 0.5)),
        "anomaly_flags":              list(tool_output.get("anomaly_flags", [])),
        "validation_notes":           tool_output.get("validation_notes") or None,
        "validated_at":               datetime.now(UTC).isoformat(),
        "model_used":                 "claude-haiku-4-5-20251001",
    }

    # Safety guard — validation block must never overwrite protected keys
    additions: dict[str, Any] = {"validation": validation_block}
    for key_name in _PROTECTED_KEYS:
        additions.pop(key_name, None)

    logger.info(
        f"[clinical_validation] validated: "
        f"confidence={validation_block['confidence_score']:.2f} "
        f"consistency={validation_block['clinical_consistency_score']:.2f} "
        f"flags={validation_block['anomaly_flags']}"
    )
    return {**analysis, **additions}
