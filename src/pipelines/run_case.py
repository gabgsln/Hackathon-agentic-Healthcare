"""Single CLI entrypoint for the full case pipeline.

DICOM input is REQUIRED.
Pipeline exits with non-zero status and a clear error message if DICOM is absent.

Steps:
    1. Validate DICOM exists              → exit(1) if missing
    2. dicom_analysis.analyze_dicom()     → analysis dict
    3. dicom_analysis.validate_analysis() → exit(1) if schema fails
    4. Write  {out}/analysis.json
    5. ingest_excel() if --excel given    → timeline dict
    6. Write  {out}/timeline.json         (only when --excel provided)
    7. generate_report.render_report()    → Markdown string
    8. Write  {out}/final_report.md

Usage:
    python -m src.pipelines.run_case \\
        --dicom  data/raw/CASE_01/image.dcm \\
        [--excel data/raw/CASE_01/data.xlsx] \\
        [--case-id CASE_01] \\
        --out    data/processed/CASE_01/
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core pipeline function (importable by tests)
# ---------------------------------------------------------------------------

def run_case(
    dicom_path: Path,
    out_dir: Path,
    case_id: str = "",
    excel_path: Path | None = None,
) -> dict[str, Path]:
    """Run the full deterministic case pipeline.

    DICOM is MANDATORY.

    Args:
        dicom_path: Path to a .dcm file.
        out_dir:    Directory where outputs are written.
        case_id:    Optional case identifier.
        excel_path: Optional Excel file (patient metadata only, no lesion sizes).

    Returns:
        Dict mapping output names to their paths:
        ``{"analysis": ..., "report": ..., "timeline": ...}``.

    Raises:
        SystemExit(1): if DICOM is missing or schema validation fails.
        ValueError:    if pixel_array cannot be read.
    """
    from src.pipelines.dicom_analysis import analyze_dicom, validate_analysis
    from src.pipelines.generate_report import render_report

    dicom_path = Path(dicom_path)
    out_dir    = Path(out_dir)

    # ── Step 1: DICOM is mandatory ────────────────────────────────────────────
    if not dicom_path.exists():
        logger.error(
            f"DICOM input is required — file not found: {dicom_path}"
        )
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    cid = case_id or dicom_path.stem

    # ── Step 2: DICOM analysis (pixel_array + metadata) ───────────────────────
    logger.info(f"[run_case] Analyzing DICOM: {dicom_path}")
    try:
        analysis = analyze_dicom(dicom_path, case_id=cid)
    except Exception as exc:
        logger.error(f"[run_case] DICOM analysis failed: {exc}")
        sys.exit(1)

    # ── Step 3: JSON Schema validation — hard fail ────────────────────────────
    logger.info("[run_case] Validating analysis against JSON Schema …")
    try:
        validate_analysis(analysis)
        logger.info("[run_case] Schema validation OK")
    except Exception as exc:
        logger.error(f"[run_case] Schema validation FAILED: {exc}")
        sys.exit(1)

    # ── Step 4: Write analysis.json ───────────────────────────────────────────
    analysis_path = out_dir / "analysis.json"
    analysis_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"[run_case] Written → {analysis_path}")

    # ── Step 5: Excel → timeline.json (optional; metadata only) ──────────────
    timeline: list[dict[str, Any]] = []
    timeline_path: Path | None = None

    if excel_path is not None:
        excel_path = Path(excel_path)
        if not excel_path.exists():
            logger.warning(
                f"[run_case] Excel file not found (skipped): {excel_path}"
            )
        else:
            from src.pipelines.ingest_excel import ingest_excel as _ingest_excel

            logger.info(f"[run_case] Ingesting Excel (metadata only): {excel_path}")
            tl_out = _ingest_excel(
                excel_path,
                case_id=cid,
                out_path=out_dir / "timeline.json",
            )
            timeline_path = tl_out
            timeline = json.loads(tl_out.read_text(encoding="utf-8"))
            logger.info(
                f"[run_case] Written → {timeline_path}  ({len(timeline)} exam(s))"
            )

    # ── Step 7: Render Markdown report ────────────────────────────────────────
    logger.info("[run_case] Rendering final report …")
    try:
        rendered = render_report(timeline, analysis)
    except Exception as exc:
        logger.error(f"[run_case] Report rendering failed: {exc}")
        sys.exit(1)

    report_path = out_dir / "final_report.md"
    report_path.write_text(rendered, encoding="utf-8")
    logger.info(
        f"[run_case] Written → {report_path}  ({len(rendered)} chars)"
    )

    outputs: dict[str, Path] = {
        "analysis": analysis_path,
        "report":   report_path,
    }
    if timeline_path:
        outputs["timeline"] = timeline_path

    logger.info(
        f"[run_case] Pipeline complete for case '{cid}'. "
        f"Outputs: {list(outputs.values())}"
    )
    return outputs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.pipelines.run_case",
        description=(
            "Full case pipeline: DICOM → analysis.json → timeline.json → final_report.md\n"
            "DICOM is REQUIRED — pipeline exits with status 1 if absent."
        ),
    )
    p.add_argument(
        "--dicom", required=True, type=Path,
        help="Path to the patient's DICOM .dcm file (REQUIRED).",
    )
    p.add_argument(
        "--excel", default=None, type=Path,
        help="Path to an Excel file with patient metadata (optional; lesion sizes ignored).",
    )
    p.add_argument(
        "--case-id", default="", dest="case_id",
        help="Case identifier (default: DICOM filename stem).",
    )
    p.add_argument(
        "--out", required=True, type=Path,
        help="Output directory where analysis.json, timeline.json, final_report.md are written.",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    # Explicit DICOM check before delegating (gives a clean error in CLI context)
    if not Path(args.dicom).exists():
        print(
            f"ERROR: DICOM input is required — file not found: {args.dicom}",
            file=sys.stderr,
        )
        sys.exit(1)

    run_case(
        dicom_path=args.dicom,
        out_dir=args.out,
        case_id=args.case_id,
        excel_path=args.excel,
    )


if __name__ == "__main__":
    main()
