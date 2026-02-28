"""Deterministic report generation from timeline + analysis JSON.

Fills src/reporting/templates/thorax_report.md via Jinja2.
No LLM is involved — this is a pure template-filling step.

Usage (CLI):
    python -m src.pipelines.generate_report \\
        --timeline data/processed/CASE_01_timeline.json \\
        --analysis data/processed/CASE_01_analysis.json \\
        --out      data/processed/CASE_01_final_report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Template directory — relative to this file's package root
_TEMPLATE_DIR = Path(__file__).parent.parent / "reporting" / "templates"
_TEMPLATE_NAME = "thorax_report.md"

PIPELINE_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _latest_section(
    timeline: list[dict[str, Any]], key: str
) -> str | None:
    """Return the most recent non-null value of report_sections[key]."""
    for exam in reversed(timeline):
        val = exam.get("report_sections", {}).get(key)
        if val:
            return val
    return None


def build_context(
    timeline: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the Jinja2 template context from pipeline data.

    Supports both:
    - Legacy Excel-timeline analysis (baseline_exam / last_exam keys)
    - Imaging-first analysis  (baseline_study / last_study keys + studies list)
    """
    def _norm_exam(d: dict) -> dict:
        """Ensure 'study_date' key is always present (legacy path uses 'date')."""
        d = d or {}
        if "study_date" not in d and "date" in d:
            d = {**d, "study_date": d["date"]}
        if "study_date" not in d:
            d = {**d, "study_date": None}
        return d

    # Unify baseline/last regardless of which analysis path produced the data
    baseline = _norm_exam(analysis.get("baseline_exam") or analysis.get("baseline_study") or {})
    last     = _norm_exam(analysis.get("last_exam")     or analysis.get("last_study")     or {})

    _default_evidence = {
        "rule_applied": "N/A",
        "progression_triggers": [],
        "response_triggers": [],
        "thresholds": {
            "progression_pct": 20.0,
            "progression_abs_mm": 5.0,
            "response_pct": 30.0,
        },
    }

    return {
        # ── meta ──────────────────────────────────────────────────────────
        "generated_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pipeline_version": PIPELINE_VERSION,
        # ── patient / exam summary ────────────────────────────────────────
        "patient_id":      analysis.get("patient_id", ""),
        "exam_count":      analysis.get("exam_count", len(timeline)),
        "first_exam_date": analysis.get("first_exam_date"),
        "last_exam_date":  analysis.get("last_exam_date"),
        "time_delta_days": analysis.get("time_delta_days"),
        # ── analysis results ──────────────────────────────────────────────
        "overall_status":  analysis.get("overall_status", "unknown"),
        "lesion_deltas":   analysis.get("lesion_deltas", []),
        "baseline_exam":   baseline,  # legacy compat
        "last_exam":       last,      # legacy compat
        "baseline_study":  baseline,  # imaging-first
        "last_study":      last,      # imaging-first
        "evidence":        analysis.get("evidence", _default_evidence),
        # ── imaging-first data ────────────────────────────────────────────
        "studies":     analysis.get("studies",     []),
        "calibration": analysis.get("calibration", {"method": "N/A", "pixel_spacing_mm": None}),
        "warnings":    analysis.get("warnings",    []),
        # ── DICOM analysis block (from dicom_analysis.py) ─────────────────
        "dicom_metadata":    (analysis.get("dicom") or {}).get("metadata"),
        "dicom_image_stats": (analysis.get("dicom") or {}).get("image_stats"),
        # ── latest pseudo-report sections ─────────────────────────────────
        # Priority: Excel timeline > LLM enrichment > None (template shows "Non disponible")
        "latest_clinical_information": (
            _latest_section(timeline, "clinical_information")
            or analysis.get("latest_clinical_information")
        ),
        "latest_study_technique": (
            _latest_section(timeline, "study_technique")
            or analysis.get("latest_study_technique")
        ),
        "latest_report": (
            _latest_section(timeline, "report")
            or analysis.get("latest_report")
        ),
        "latest_conclusions": (
            _latest_section(timeline, "conclusions")
            or analysis.get("latest_conclusions")
        ),
        # ── KPIs (all keys always present; None when not computable) ──────
        "kpi": {
            "sum_diameters_baseline_mm":   analysis.get("kpi", {}).get("sum_diameters_baseline_mm"),
            "sum_diameters_current_mm":    analysis.get("kpi", {}).get("sum_diameters_current_mm"),
            "sum_diameters_delta_pct":     analysis.get("kpi", {}).get("sum_diameters_delta_pct"),
            "dominant_lesion_baseline_mm": analysis.get("kpi", {}).get("dominant_lesion_baseline_mm"),
            "dominant_lesion_current_mm":  analysis.get("kpi", {}).get("dominant_lesion_current_mm"),
            "dominant_lesion_delta_pct":   analysis.get("kpi", {}).get("dominant_lesion_delta_pct"),
            "lesion_count_baseline":       analysis.get("kpi", {}).get("lesion_count_baseline", 0),
            "lesion_count_current":        analysis.get("kpi", {}).get("lesion_count_current", 0),
            "lesion_count_delta":          analysis.get("kpi", {}).get("lesion_count_delta", 0),
            "growth_rate_mm_per_day":      analysis.get("kpi", {}).get("growth_rate_mm_per_day"),
            "data_completeness_score":     analysis.get("kpi", {}).get("data_completeness_score", 0.0),
        },
    }


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render_report(
    timeline: list[dict[str, Any]],
    analysis: dict[str, Any],
    template_dir: Path = _TEMPLATE_DIR,
    template_name: str = _TEMPLATE_NAME,
) -> str:
    """Render the Markdown report. Returns the rendered string."""
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_name)
    context = build_context(timeline, analysis)
    return template.render(**context)


def generate_report(
    timeline_path: Path,
    analysis_path: Path,
    out_path: Path | None = None,
) -> Path:
    """Load inputs, render the report, write to disk.

    Returns the path of the written Markdown file.
    """
    timeline: list[dict] = json.loads(timeline_path.read_text(encoding="utf-8"))
    analysis: dict = json.loads(analysis_path.read_text(encoding="utf-8"))

    print(
        f"[generate_report] {len(timeline)} exam(s), "
        f"status={analysis.get('overall_status', '?')}"
    )

    rendered = render_report(timeline, analysis)

    # Default output path
    if out_path is None:
        case_id = analysis_path.stem.replace("_analysis", "")
        out_path = analysis_path.parent / f"{case_id}_final_report.md"

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"[generate_report] Written → {out_path}  ({len(rendered)} chars)")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.pipelines.generate_report",
        description="Fill the Markdown report template from timeline + analysis JSON.",
    )
    p.add_argument("--timeline", required=True, type=Path, help="*_timeline.json path.")
    p.add_argument("--analysis", required=True, type=Path, help="*_analysis.json path.")
    p.add_argument("--out", default=None, type=Path, help="Output .md path (optional).")
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    for p in (args.timeline, args.analysis):
        if not Path(p).exists():
            print(f"[generate_report] ERROR: file not found: {p}", file=sys.stderr)
            sys.exit(1)

    try:
        out = generate_report(
            timeline_path=Path(args.timeline),
            analysis_path=Path(args.analysis),
            out_path=args.out,
        )
        print(f"[generate_report] Done → {out}")
    except Exception as exc:
        print(f"[generate_report] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
