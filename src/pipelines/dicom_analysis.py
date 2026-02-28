"""Full DICOM analysis: metadata extraction + pixel statistics + JSON Schema validation.

Accepts either:
  - a single .dcm file  → input_kind="single", n_slices=1
  - a folder of slices  → input_kind="series", n_slices=N

Non-image objects (SR, SEG, RTSTRUCT, RTDOSE, RTPLAN, PR, KO) are rejected
with a clear ValueError before any pixel data is touched.

New top-level block added to every analysis dict:
  "imaging": {
      "input_kind": "single" | "series",
      "n_slices": int,
      "volume_shape": [z, y, x],
      "spacing_mm": [z, y, x],          # None where unavailable
      "series_instance_uid": str | null,
      "sorting_key_used": "InstanceNumber" | "ImagePositionPatient" | "none",
      "is_3d": bool
  }

Every analysis dict also carries:
  "status_reason":      str   — why overall_status has its value
  "status_explanation": str   — human-readable French explanation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

_SCHEMA_PATH = Path(__file__).parent.parent.parent / "data" / "schema" / "analysis_schema.json"

_PROGRESSION_PCT: float = 20.0
_PROGRESSION_ABS: float = 5.0
_RESPONSE_PCT:    float = 30.0

_NON_IMAGE_MODALITIES: frozenset[str] = frozenset({
    "SR", "SEG", "RTSTRUCT", "RTDOSE", "RTPLAN", "PR", "KO",
    "AU", "ECG", "EPS", "HD", "IO", "OAM", "OP", "OPM", "OPT", "OPV",
    "OSS", "PX", "RG", "SM", "SRF", "TG", "XC",
})

_MAX_SAMPLE_SLICES: int = 16


# ---------------------------------------------------------------------------
# Metadata helpers
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
    """Extract structured metadata from a pydicom Dataset."""
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
# Non-image gating
# ---------------------------------------------------------------------------

def _check_image_modality(ds: Any, path: Path) -> None:
    """Raise ValueError if DICOM is a non-image object (SR, SEG, RTSTRUCT, …)."""
    modality = _str_tag(ds, "Modality", "").upper()
    if modality in _NON_IMAGE_MODALITIES:
        raise ValueError(
            f"Non-image DICOM rejected (Modality={modality!r}): {path}. "
            "Only image modalities (CT, MR, PT, DX, CR, NM, …) are supported."
        )


# ---------------------------------------------------------------------------
# Series helpers
# ---------------------------------------------------------------------------

def _collect_series_files(folder: Path) -> list[Path]:
    """Return candidate DICOM files in *folder* (recursive)."""
    dcm = sorted(folder.rglob("*.dcm"))
    if dcm:
        return dcm
    return sorted(f for f in folder.rglob("*") if f.is_file() and not f.suffix)


def _sort_slices(items: list[tuple[Path, Any]]) -> tuple[list[tuple[Path, Any]], str]:
    """Sort (path, ds) pairs by InstanceNumber or ImagePositionPatient[2]."""
    if all(getattr(ds, "InstanceNumber", None) is not None for _, ds in items):
        return sorted(items, key=lambda x: int(getattr(x[1], "InstanceNumber", 0))), "InstanceNumber"

    def _z(ds: Any) -> float:
        try:
            ipp = getattr(ds, "ImagePositionPatient", None)
            return float(ipp[2]) if ipp and len(ipp) >= 3 else 0.0
        except Exception:
            return 0.0

    if any(getattr(ds, "ImagePositionPatient", None) is not None for _, ds in items):
        return sorted(items, key=lambda x: _z(x[1])), "ImagePositionPatient"

    return items, "none"


def _compute_z_spacing(items: list[tuple[Path, Any]]) -> float | None:
    if not items:
        return None
    if len(items) == 1:
        return _float_tag(items[0][1], "SliceThickness")
    try:
        z_vals = []
        for _, ds in items:
            ipp = getattr(ds, "ImagePositionPatient", None)
            if ipp and len(ipp) >= 3:
                z_vals.append(float(ipp[2]))
        if len(z_vals) >= 2:
            gaps = [abs(z_vals[i + 1] - z_vals[i]) for i in range(len(z_vals) - 1)]
            return round(sum(gaps) / len(gaps), 4)
    except Exception:
        pass
    return _float_tag(items[0][1], "SliceThickness")


# ---------------------------------------------------------------------------
# Image statistics
# ---------------------------------------------------------------------------

def _metadata_completeness(metadata: dict[str, Any]) -> float:
    fields = ["PatientID", "StudyInstanceUID", "SeriesInstanceUID", "Modality", "StudyDate", "PixelSpacing"]
    present = sum(1 for f in fields if metadata.get(f))
    return round(present / len(fields), 3)


def _consistency_score(mn: float, mx: float, std: float, size: int, meta_score: float) -> float:
    score = 1.0
    if mx <= mn:
        score -= 0.4
    elif (mx - mn) < 10:
        score -= 0.2
    if size < 64 * 64:
        score -= 0.2
    if std < 1.0:
        score -= 0.2
    return round(max(0.0, min(1.0, score * 0.7 + meta_score * 0.3)), 3)


def extract_image_stats(ds: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    """Compute image statistics from a single ds.pixel_array.

    Raises:
        ValueError: if pixel_array cannot be read.
    """
    try:
        arr = ds.pixel_array.astype(np.float32)
    except Exception as exc:
        raise ValueError(f"Cannot read pixel_array from DICOM: {exc}") from exc

    mn, mx, mean, std = float(arr.min()), float(arr.max()), float(arr.mean()), float(arr.std())

    return {
        "shape":                  list(arr.shape),
        "dtype":                  str(arr.dtype),
        "min":                    round(mn, 4),
        "max":                    round(mx, 4),
        "mean":                   round(mean, 4),
        "std":                    round(std, 4),
        "data_consistency_score": _consistency_score(mn, mx, std, arr.size, _metadata_completeness(metadata)),
    }


def _compute_series_pixel_stats(
    sorted_paths: list[Path],
    metadata: dict[str, Any],
    max_sample: int = _MAX_SAMPLE_SLICES,
) -> dict[str, Any]:
    """Series-wide pixel statistics sampled over at most *max_sample* slices."""
    import pydicom

    n = len(sorted_paths)
    if n <= max_sample:
        sample = sorted_paths
    else:
        step = n / max_sample
        sample = [sorted_paths[int(i * step)] for i in range(max_sample)]

    arrays: list[np.ndarray] = []
    for path in sample:
        try:
            ds = pydicom.dcmread(str(path))
            arrays.append(ds.pixel_array.astype(np.float32))
        except Exception:
            continue

    if not arrays:
        raise ValueError("Could not read pixel data from any slice in the series.")

    flat = np.concatenate([a.ravel() for a in arrays])
    mn, mx, mean, std = float(flat.min()), float(flat.max()), float(flat.mean()), float(flat.std())
    rows, cols = arrays[0].shape

    return {
        "shape":                  [n, rows, cols],
        "dtype":                  str(arrays[0].dtype),
        "min":                    round(mn, 4),
        "max":                    round(mx, 4),
        "mean":                   round(mean, 4),
        "std":                    round(std, 4),
        "data_consistency_score": _consistency_score(mn, mx, std, flat.size, _metadata_completeness(metadata)),
        "sampled_slices":         len(arrays),
    }


# ---------------------------------------------------------------------------
# Imaging block
# ---------------------------------------------------------------------------

def _build_imaging_block(
    input_kind: str,
    n_slices: int,
    image_stats: dict[str, Any],
    metadata: dict[str, Any],
    z_spacing: float | None,
    sorting_key: str,
) -> dict[str, Any]:
    shape = image_stats["shape"]
    rows = shape[-2] if len(shape) >= 3 else (shape[0] if len(shape) == 2 else None)
    cols = shape[-1] if len(shape) >= 1 else None
    px = metadata.get("PixelSpacing") or []
    y_sp = round(float(px[0]), 4) if len(px) >= 2 else None
    x_sp = round(float(px[1]), 4) if len(px) >= 2 else None

    return {
        "input_kind":          input_kind,
        "n_slices":            n_slices,
        "volume_shape":        [n_slices, rows, cols],
        "spacing_mm":          [z_spacing, y_sp, x_sp],
        "series_instance_uid": metadata.get("SeriesInstanceUID") or None,
        "sorting_key_used":    sorting_key,
        "is_3d":               n_slices > 1,
    }


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_analysis(analysis: dict[str, Any]) -> None:
    """Validate *analysis* against ``data/schema/analysis_schema.json``."""
    import jsonschema

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
# Public entry point
# ---------------------------------------------------------------------------

def analyze_dicom(
    dicom_input: Path,
    case_id: str = "",
) -> dict[str, Any]:
    """Analyze a single .dcm file OR a folder of DICOM slices.

    Args:
        dicom_input: Path to a .dcm file or a directory containing DICOM slices.
        case_id:     Identifier echoed into the output dict.

    Returns:
        Analysis dict including ``imaging``, ``status_reason``, ``status_explanation``.

    Raises:
        FileNotFoundError: if dicom_input does not exist.
        ValueError:        if modality is non-image or pixel data is unreadable.
    """
    import pydicom

    dicom_input = Path(dicom_input)
    if not dicom_input.exists():
        raise FileNotFoundError(f"DICOM input is required — file not found: {dicom_input}")

    if dicom_input.is_file():
        return _analyze_single_file(dicom_input, case_id, pydicom)
    return _analyze_series_folder(dicom_input, case_id, pydicom)


def _analyze_single_file(path: Path, case_id: str, pydicom: Any) -> dict[str, Any]:
    print(f"[dicom_analysis] Reading single file: {path} …")
    ds = pydicom.dcmread(str(path))
    _check_image_modality(ds, path)

    metadata    = extract_metadata(ds)
    image_stats = extract_image_stats(ds, metadata)
    z_sp        = _float_tag(ds, "SliceThickness")
    imaging     = _build_imaging_block("single", 1, image_stats, metadata, z_sp, "none")

    print(
        f"[dicom_analysis] single | PatientID={metadata['PatientID'] or 'N/A'} "
        f"Modality={metadata['Modality'] or 'N/A'} "
        f"shape={image_stats['shape']} consistency={image_stats['data_consistency_score']:.2f}"
    )

    return _build_analysis_dict(
        case_id=case_id or path.stem,
        metadata=metadata,
        image_stats=image_stats,
        imaging=imaging,
        status_reason="no_timeline",
        status_explanation="Analyse d'un fichier DICOM unique — aucune comparaison temporelle disponible.",
    )


def _analyze_series_folder(folder: Path, case_id: str, pydicom: Any) -> dict[str, Any]:
    print(f"[dicom_analysis] Scanning series folder: {folder} …")
    files = _collect_series_files(folder)
    if not files:
        raise FileNotFoundError(f"No DICOM files found in folder: {folder}")

    items: list[tuple[Path, Any]] = []
    for f in files:
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True)
            _check_image_modality(ds, f)
            items.append((f, ds))
        except ValueError:
            raise
        except Exception:
            continue

    if not items:
        raise ValueError(f"No valid image-modality DICOM files found in: {folder}")

    groups: dict[str, list[tuple[Path, Any]]] = {}
    for f, ds in items:
        uid = _str_tag(ds, "SeriesInstanceUID", "__none__")
        groups.setdefault(uid, []).append((f, ds))

    largest = max(groups.values(), key=len)
    sorted_items, sort_key = _sort_slices(largest)
    z_spacing = _compute_z_spacing(sorted_items)

    _, ref_ds = sorted_items[0]
    metadata = extract_metadata(ref_ds)

    sorted_paths = [p for p, _ in sorted_items]
    image_stats  = _compute_series_pixel_stats(sorted_paths, metadata)
    n_slices     = len(sorted_items)
    imaging      = _build_imaging_block("series", n_slices, image_stats, metadata, z_spacing, sort_key)

    print(
        f"[dicom_analysis] series | {n_slices} slices | "
        f"PatientID={metadata['PatientID'] or 'N/A'} "
        f"Modality={metadata['Modality'] or 'N/A'} "
        f"sorted_by={sort_key} consistency={image_stats['data_consistency_score']:.2f}"
    )

    return _build_analysis_dict(
        case_id=case_id or folder.name,
        metadata=metadata,
        image_stats=image_stats,
        imaging=imaging,
        status_reason="no_timeline",
        status_explanation=(
            f"Série de {n_slices} coupes DICOM analysée — "
            "aucune comparaison temporelle disponible (timeline manquante)."
        ),
    )


def _build_analysis_dict(
    *,
    case_id: str,
    metadata: dict[str, Any],
    image_stats: dict[str, Any],
    imaging: dict[str, Any],
    status_reason: str,
    status_explanation: str,
) -> dict[str, Any]:
    return {
        "case_id":            case_id,
        "patient_id":         metadata.get("PatientID", ""),
        "overall_status":     "unknown",
        "status_reason":      status_reason,
        "status_explanation": status_explanation,
        "evidence": {
            "rule_applied": "unknown: DICOM analysis only — no comparative timeline available",
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
            "data_completeness_score":     round(image_stats["data_consistency_score"] * 100, 1),
        },
        "dicom": {
            "metadata":    metadata,
            "image_stats": image_stats,
        },
        "imaging": imaging,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.pipelines.dicom_analysis",
        description=(
            "Extract DICOM metadata + pixel statistics, validate against schema. "
            "Accepts a .dcm file or a folder of slices."
        ),
    )
    p.add_argument("--dicom", required=True, type=Path, help="Path to a .dcm file or a folder of DICOM slices (REQUIRED).")
    p.add_argument("--case-id", default="", dest="case_id", help="Case identifier (default: file/folder name).")
    p.add_argument("--out", default=None, type=Path, help="Output analysis.json path.")
    p.add_argument("--no-validate", action="store_true", help="Skip JSON Schema validation.")
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    dicom_input = Path(args.dicom)
    if not dicom_input.exists():
        print(f"[dicom_analysis] ERROR: not found: {dicom_input}", file=sys.stderr)
        sys.exit(1)

    try:
        analysis = analyze_dicom(dicom_input, case_id=args.case_id)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[dicom_analysis] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not args.no_validate:
        try:
            validate_analysis(analysis)
            print("[dicom_analysis] Schema validation OK")
        except Exception as exc:
            print(f"[dicom_analysis] SCHEMA ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    stem = analysis["case_id"]
    out_path = args.out or dicom_input.parent / f"{stem}_analysis.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[dicom_analysis] Written → {out_path}")


if __name__ == "__main__":
    main()
