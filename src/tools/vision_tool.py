"""Vision tool — imaging-first deterministic lesion measurement pipeline.

Accepts:
  (A) Local DICOM file paths / folder paths
  (B) Orthanc study IDs (downloads via download_study then unzips)

Measurement path (hackathon minimal):
  - Requires an annotations JSON with pixel-space lesion measurements
    + SeriesInstanceUID reference for PixelSpacing lookup.
  - Converts pixels → mm using PixelSpacing from DICOM metadata.
  - Hard-fails with a structured error if no measurements can be derived.

Annotation JSON schema:
  [
    {
      "study_id": "<orthanc_uid or local label>",
      "series_uid": "<SeriesInstanceUID>",
      "lesions": [
        {
          "lesion_id": "L1",
          "slice_instance": 123,
          "long_axis_px": 120,
          "short_axis_px": 70
        }
      ]
    }
  ]

Output schema:
  {
    "studies": [
      {
        "study_uid": "...",
        "study_date": "YYYY-MM-DD",
        "patient_id": "...",
        "series_count": N,
        "lesions": [
          {
            "lesion_id": "L1",
            "slice_instance": 123,
            "long_axis_px": 120, "short_axis_px": 70,
            "long_axis_mm": 12.3, "short_axis_mm": 7.1,
            "series_uid": "..."
          }
        ],
        "kpis": {
          "sum_long_axis_mm": 12.3,
          "dominant_lesion_mm": 12.3,
          "lesion_count": 1
        }
      }
    ],
    "warnings": [...],
    "calibration": {
      "method": "dicom_spacing",
      "pixel_spacing_mm": [sx, sy]
    }
  }
"""
from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from src.imaging.dicom_utils import read_dicom_metadata
from src.imaging.orthanc_utils import download_study

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scan_dcm_files(folder: Path) -> list[Path]:
    """Recursively find all .dcm files in *folder*."""
    return sorted(folder.rglob("*.dcm")) + sorted(
        p for p in folder.rglob("*.DCM")
        if p not in set(folder.rglob("*.dcm"))
    )


def _build_study_meta(dcm_files: list[Path]) -> dict[str, Any]:
    """Build study-level summary: group by SeriesInstanceUID, capture patient/date."""
    series: dict[str, dict[str, Any]] = {}
    patient_id = ""
    study_date = ""
    study_uid = ""

    for f in dcm_files:
        try:
            meta = read_dicom_metadata(f)
        except Exception:
            continue

        if not patient_id:
            patient_id = meta.get("PatientID", "") or ""
        if not study_date:
            study_date = meta.get("StudyDate", "") or ""
        if not study_uid:
            study_uid = meta.get("StudyInstanceUID", "") or ""

        sid = meta.get("SeriesInstanceUID", "")
        if sid not in series:
            series[sid] = {
                "series_uid":         sid,
                "modality":           meta.get("Modality", ""),
                "pixel_spacing":      meta.get("PixelSpacing"),
                "file_count":         0,
                "representative_file": str(f),
            }
        series[sid]["file_count"] += 1

    return {
        "patient_id": patient_id,
        "study_date": study_date,
        "study_uid":  study_uid,
        "series":     list(series.values()),
    }


def _resolve_pixel_spacing(
    series_map: dict[str, dict[str, Any]],
    series_uid: str,
) -> tuple[float, float] | None:
    """Return (sx, sy) mm for the given series_uid, or None."""
    s = series_map.get(series_uid)
    if s and s.get("pixel_spacing"):
        ps = s["pixel_spacing"]
        return float(ps[0]), float(ps[1])
    return None


def _hard_fail(detail: str) -> None:
    """Raise ValueError with a structured JSON error payload."""
    raise ValueError(json.dumps({
        "error":  "MEASUREMENTS_REQUIRED",
        "detail": detail,
    }))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_vision_tool(
    dicom_paths: list[str | Path] | None = None,
    orthanc_study_ids: list[str] | None = None,
    annotations: list[dict[str, Any]] | None = None,
    annotations_json_str: str | None = None,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the imaging-first measurement pipeline.

    Args:
        dicom_paths:          Local .dcm files or folders.
        orthanc_study_ids:    Orthanc study UUIDs — downloaded before processing.
        annotations:          Pre-parsed annotation list (pixel coords).
        annotations_json_str: Raw JSON string of annotations (alternative to above).
        work_dir:             Base dir for Orthanc downloads (default: system tempdir).

    Returns:
        Structured dict with "studies", "warnings", "calibration".

    Raises:
        ValueError: structured JSON with ``error="MEASUREMENTS_REQUIRED"`` when
                    measurements cannot be derived.
    """
    warnings: list[str] = []
    studies_out: list[dict[str, Any]] = []

    # ── Parse annotations ─────────────────────────────────────────────────────
    if annotations_json_str and not annotations:
        try:
            annotations = json.loads(annotations_json_str)
        except json.JSONDecodeError as e:
            _hard_fail(f"Invalid annotations JSON: {e}")

    ann_by_study: dict[str, list[dict[str, Any]]] = {}
    if annotations:
        for entry in annotations:
            sid = entry.get("study_id", "__default__")
            ann_by_study[sid] = entry.get("lesions", [])

    # No annotations at all → fail immediately with clear message
    if not ann_by_study:
        _hard_fail(
            "No lesion measurements available. "
            "Provide annotations (px) or DICOM SR/RTSTRUCT."
        )

    # ── Resolve DICOM sources ─────────────────────────────────────────────────
    all_folders: list[Path] = []

    if orthanc_study_ids:
        tmp_root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="vision_"))
        for study_id in orthanc_study_ids:
            zip_path = download_study(study_id, out_dir=tmp_root)
            extract_dir = tmp_root / f"study_{study_id[:8]}"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)
            all_folders.append(extract_dir)

    if dicom_paths:
        for p in dicom_paths:
            pp = Path(p)
            if pp.is_dir():
                all_folders.append(pp)
            elif pp.is_file() and pp.suffix.lower() in (".dcm", ""):
                all_folders.append(pp.parent)

    if not all_folders:
        _hard_fail("No DICOM sources provided. Supply dicom_paths or orthanc_study_ids.")

    # ── Process each folder as one study ─────────────────────────────────────
    last_calibration: dict[str, Any] = {"method": "dicom_spacing", "pixel_spacing_mm": None}

    for folder in all_folders:
        dcm_files = _scan_dcm_files(folder)
        if not dcm_files:
            warnings.append(f"No .dcm files found in {folder}")
            continue

        study_meta = _build_study_meta(dcm_files)
        series_map = {s["series_uid"]: s for s in study_meta["series"]}

        # Match annotations to this study (by study_uid, study_date, or __default__)
        study_key = study_meta["study_uid"] or study_meta["study_date"] or str(folder)
        ann_lesions: list[dict[str, Any]] = (
            ann_by_study.get(study_key)
            or ann_by_study.get("__default__")
            or []
        )

        if not ann_lesions:
            warnings.append(
                f"No annotations matched study {study_key[:20]} — study skipped."
            )
            continue

        # ── Convert px → mm ───────────────────────────────────────────────────
        lesions_out: list[dict[str, Any]] = []

        for ann in ann_lesions:
            ann_series_uid = ann.get("series_uid", "")
            ps = _resolve_pixel_spacing(series_map, ann_series_uid)

            if ps is None:
                # Fall back to first CT series with spacing
                for s in study_meta["series"]:
                    if s.get("modality") == "CT" and s.get("pixel_spacing"):
                        raw_ps = s["pixel_spacing"]
                        ps = (float(raw_ps[0]), float(raw_ps[1]))
                        warnings.append(
                            f"Series UID not matched for lesion "
                            f"{ann.get('lesion_id', '?')}, "
                            f"using first CT series spacing."
                        )
                        break

            if ps is None:
                warnings.append(
                    f"No PixelSpacing found for lesion "
                    f"{ann.get('lesion_id', '?')} — skipping."
                )
                continue

            sx, sy = ps
            last_calibration["pixel_spacing_mm"] = [sx, sy]

            long_px  = ann.get("long_axis_px")
            short_px = ann.get("short_axis_px")
            long_mm  = round(long_px  * sx, 2) if long_px  is not None else None
            short_mm = round(short_px * sy, 2) if short_px is not None else None

            lesions_out.append({
                "lesion_id":      ann.get("lesion_id", f"L{len(lesions_out) + 1}"),
                "slice_instance": ann.get("slice_instance"),
                "long_axis_px":   long_px,
                "short_axis_px":  short_px,
                "long_axis_mm":   long_mm,
                "short_axis_mm":  short_mm,
                "series_uid":     ann_series_uid,
            })

        if not lesions_out:
            _hard_fail(
                "No lesion measurements could be derived. "
                "Check annotations JSON and PixelSpacing availability."
            )

        # ── KPIs ──────────────────────────────────────────────────────────────
        long_axes = [
            les["long_axis_mm"] for les in lesions_out if les["long_axis_mm"] is not None
        ]
        kpis: dict[str, Any] = {
            "sum_long_axis_mm":   round(sum(long_axes), 2) if long_axes else None,
            "dominant_lesion_mm": max(long_axes)           if long_axes else None,
            "lesion_count":       len(lesions_out),
        }

        studies_out.append({
            "study_uid":     study_meta["study_uid"],
            "study_date":    study_meta["study_date"],
            "patient_id":    study_meta["patient_id"],
            "series_count":  len(study_meta["series"]),
            "lesions":       lesions_out,
            "kpis":          kpis,
        })

    if not studies_out:
        _hard_fail("No valid studies could be processed from the provided DICOM sources.")

    return {
        "studies":     studies_out,
        "warnings":    warnings,
        "calibration": last_calibration,
    }
