"""Full DICOM analysis: metadata extraction + pixel statistics + JSON Schema validation.

DICOM is MANDATORY. Fails with non-zero exit status if file is missing or unreadable.

Extracted metadata:
  PatientID, StudyInstanceUID, SeriesInstanceUID, Modality, BodyPartExamined,
  StudyDate, SeriesDescription, InstanceNumber, PixelSpacing, SliceThickness

Computed image statistics (from pixel_array):
  shape, dtype, min, max, mean, std, data_consistency_score (0–1)

JSON Schema validation:
  Validates the output dict against data/schema/analysis_schema.json.
  Raises jsonschema.ValidationError with exact field path on failure.

Usage (CLI):
    python -m src.pipelines.dicom_analysis \\
        --dicom data/raw/CASE_01/image.dcm \\
        [--case-id CASE_01] \\
        --out   data/processed/CASE_01_analysis.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

# JSON Schema path — relative to this file's package root
_SCHEMA_PATH = Path(__file__).parent.parent.parent / "data" / "schema" / "analysis_schema.json"

# RECIST thresholds (echoed into evidence block)
_PROGRESSION_PCT: float = 20.0
_PROGRESSION_ABS: float = 5.0
_RESPONSE_PCT:    float = 30.0


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def _str_tag(ds: Any, tag: str, default: str = "") -> str:
    try:
        val = getattr(ds, tag, None)
        return str(val).strip() if val is not None else default
    except Exception:
        return default


def _int_tag(ds: Any, tag: str) -> int | None:
    try:
        val = getattr(ds, tag, None)
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _float_tag(ds: Any, tag: str) -> float | None:
    try:
        val = getattr(ds, tag, None)
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _parse_dicom_date(raw: str) -> str | None:
    s = (raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def extract_metadata(ds: Any) -> dict[str, Any]:
    """Extract structured metadata from a pydicom Dataset.

    Returns a dict matching the ``dicom.metadata`` block of the analysis schema.
    """
    pixel_spacing: list[float] | None = None
    try:
        ps = getattr(ds, "PixelSpacing", None)
        if ps is not None and len(ps) >= 2:
            pixel_spacing = [float(ps[0]), float(ps[1])]
    except Exception:
        pass

    return {
        "PatientID":         _str_tag(ds, "PatientID"),
        "StudyInstanceUID":  _str_tag(ds, "StudyInstanceUID"),
        "SeriesInstanceUID": _str_tag(ds, "SeriesInstanceUID"),
        "Modality":          _str_tag(ds, "Modality"),
        "BodyPartExamined":  _str_tag(ds, "BodyPartExamined") or None,
        "StudyDate":         _parse_dicom_date(_str_tag(ds, "StudyDate")),
        "SeriesDescription": _str_tag(ds, "SeriesDescription") or None,
        "InstanceNumber":    _int_tag(ds, "InstanceNumber"),
        "PixelSpacing":      pixel_spacing,
        "SliceThickness":    _float_tag(ds, "SliceThickness"),
    }


# ---------------------------------------------------------------------------
# Image statistics
# ---------------------------------------------------------------------------

def _metadata_completeness(metadata: dict[str, Any]) -> float:
    """Score 0–1 based on how many metadata fields are populated."""
    fields = [
        "PatientID", "StudyInstanceUID", "SeriesInstanceUID",
        "Modality", "StudyDate", "PixelSpacing",
    ]
    present = sum(1 for f in fields if metadata.get(f))
    return round(present / len(fields), 3)


def extract_image_stats(ds: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    """Compute image statistics from ds.pixel_array.

    pixel_array is actively loaded — not optional.

    Returns a dict matching the ``dicom.image_stats`` block of the analysis schema.

    Raises:
        ValueError: if pixel_array cannot be read.
    """
    try:
        arr = ds.pixel_array.astype(np.float32)
    except Exception as exc:
        raise ValueError(
            f"Cannot read pixel_array from DICOM: {exc}"
        ) from exc

    mn = float(arr.min())
    mx = float(arr.max())
    mean = float(arr.mean())
    std  = float(arr.std())

    # --- data_consistency_score (0.0 – 1.0) --------------------------------
    # Deductions for clearly invalid data
    score = 1.0
    if mx <= mn:                   # constant / blank image
        score -= 0.4
    elif (mx - mn) < 10:           # nearly flat (probably background)
        score -= 0.2
    if arr.size < 64 * 64:         # suspiciously small
        score -= 0.2
    if std < 1.0:                  # near-zero variance
        score -= 0.2
    # bonus/penalty for metadata completeness
    meta_score = _metadata_completeness(metadata)
    score = score * 0.7 + meta_score * 0.3  # weighted blend
    score = round(max(0.0, min(1.0, score)), 3)

    return {
        "shape":                 list(arr.shape),
        "dtype":                 str(arr.dtype),
        "min":                   round(mn, 4),
        "max":                   round(mx, 4),
        "mean":                  round(mean, 4),
        "std":                   round(std, 4),
        "data_consistency_score": score,
    }


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_analysis(analysis: dict[str, Any]) -> None:
    """Validate *analysis* against ``data/schema/analysis_schema.json``.

    Raises:
        jsonschema.ValidationError: with exact failing field path in the message.
        FileNotFoundError: if the schema file is missing.
    """
    import jsonschema  # late import

    if not _SCHEMA_PATH.exists():
        raise FileNotFoundError(f"JSON Schema not found: {_SCHEMA_PATH}")

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(instance=analysis, schema=schema)
    except jsonschema.ValidationError as exc:
        field_path = " → ".join(str(p) for p in exc.absolute_path) or "<root>"
        raise jsonschema.ValidationError(
            f"Schema validation FAILED at [{field_path}]: {exc.message}"
        ) from exc


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_dicom(
    dicom_path: Path,
    case_id: str = "",
) -> dict[str, Any]:
    """Run full DICOM analysis on a single .dcm file.

    DICOM is MANDATORY — raises FileNotFoundError if the path does not exist.
    Pixel data is always loaded (pixel_array).

    Args:
        dicom_path: Path to a .dcm file.
        case_id:    Identifier echoed into the output dict.

    Returns:
        Analysis dict ready for JSON Schema validation and report generation.

    Raises:
        FileNotFoundError: if dicom_path does not exist.
        ValueError:        if pixel_array cannot be read.
    """
    import pydicom  # late import

    if not Path(dicom_path).exists():
        raise FileNotFoundError(
            f"DICOM input is required — file not found: {dicom_path}"
        )

    print(f"[dicom_analysis] Reading {dicom_path} …")
    ds = pydicom.dcmread(str(dicom_path))  # loads pixel data by default

    metadata    = extract_metadata(ds)
    image_stats = extract_image_stats(ds, metadata)

    print(
        f"[dicom_analysis] "
        f"PatientID={metadata['PatientID'] or 'N/A'}  "
        f"Modality={metadata['Modality'] or 'N/A'}  "
        f"shape={image_stats['shape']}  "
        f"consistency={image_stats['data_consistency_score']:.2f}"
    )

    # Build the full analysis dict (RECIST status is unknown for a single DICOM instance)
    analysis: dict[str, Any] = {
        "case_id":    case_id or Path(dicom_path).stem,
        "patient_id": metadata.get("PatientID", ""),
        "overall_status": "unknown",
        "evidence": {
            "rule_applied": (
                "unknown: single DICOM instance — "
                "no comparative analysis possible"
            ),
            "progression_triggers": [],
            "response_triggers":    [],
            "thresholds": {
                "progression_pct":    _PROGRESSION_PCT,
                "progression_abs_mm": _PROGRESSION_ABS,
                "response_pct":       _RESPONSE_PCT,
            },
        },
        "lesion_deltas": [],
        "kpi": {
            "sum_diameters_baseline_mm":   None,
            "sum_diameters_current_mm":    None,
            "sum_diameters_delta_pct":     None,
            "dominant_lesion_baseline_mm": None,
            "dominant_lesion_current_mm":  None,
            "dominant_lesion_delta_pct":   None,
            "lesion_count_baseline":       0,
            "lesion_count_current":        0,
            "lesion_count_delta":          0,
            "growth_rate_mm_per_day":      None,
            # data_completeness_score in 0–100; image_stats uses 0–1
            "data_completeness_score": round(
                image_stats["data_consistency_score"] * 100, 1
            ),
        },
        "dicom": {
            "metadata":    metadata,
            "image_stats": image_stats,
        },
    }

    return analysis


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.pipelines.dicom_analysis",
        description="Extract DICOM metadata + pixel statistics, validate against schema.",
    )
    p.add_argument(
        "--dicom", required=True, type=Path,
        help="Path to a .dcm file (REQUIRED).",
    )
    p.add_argument(
        "--case-id", default="", dest="case_id",
        help="Case identifier echoed into output (default: DICOM file stem).",
    )
    p.add_argument(
        "--out", default=None, type=Path,
        help="Output analysis.json path (default: same dir as DICOM).",
    )
    p.add_argument(
        "--no-validate", action="store_true",
        help="Skip JSON Schema validation (not recommended).",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    dicom_path = Path(args.dicom)
    if not dicom_path.exists():
        print(
            f"[dicom_analysis] ERROR: DICOM input is required — "
            f"file not found: {dicom_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        analysis = analyze_dicom(dicom_path, case_id=args.case_id)
    except (ValueError, Exception) as exc:
        print(f"[dicom_analysis] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not args.no_validate:
        try:
            validate_analysis(analysis)
            print("[dicom_analysis] Schema validation OK")
        except Exception as exc:
            print(f"[dicom_analysis] SCHEMA ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    out_path = args.out or dicom_path.parent / f"{analysis['case_id']}_analysis.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[dicom_analysis] Written → {out_path}")


if __name__ == "__main__":
    main()
