"""DICOM utilities with full pixel support — server-side (no plotting).

Extends src/pipelines/dicom_utils.py (metadata-only) by adding:
- read_dicom_metadata(path)  — enriched tag set required by vision_tool
- load_pixel_spacing(ds)     — (sx, sy) in mm
- normalize_pixel_array(ds)  — float32 ndarray in [0, 1]
- show_dicom(path)           — metadata-only version of the WELCOME.ipynb function
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

def _str_tag(ds: Any, tag: str, default: str = "") -> str:
    try:
        val = getattr(ds, tag, None)
        return str(val).strip() if val is not None else default
    except Exception:
        return default


def _parse_dicom_date(raw: str) -> str | None:
    """Convert DICOM YYYYMMDD → ISO YYYY-MM-DD."""
    s = (raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_pixel_spacing(ds: Any) -> tuple[float, float] | None:
    """Return (row_spacing_mm, col_spacing_mm) from PixelSpacing tag, or None.

    Args:
        ds: pydicom Dataset (already loaded).
    """
    try:
        ps = getattr(ds, "PixelSpacing", None)
        if ps is not None and len(ps) >= 2:
            return float(ps[0]), float(ps[1])
    except Exception:
        pass
    return None


def normalize_pixel_array(ds: Any) -> np.ndarray:
    """Return pixel array as float32 in [0, 1].

    Args:
        ds: pydicom Dataset loaded WITH pixel data.
    """
    arr = ds.pixel_array.astype(np.float32)
    mn, mx = arr.min(), arr.max()
    return (arr - mn) / (mx - mn + 1e-8)


def read_dicom_metadata(path: str | Path) -> dict[str, Any]:
    """Read a DICOM file and return a structured metadata dict.

    This is the enriched version needed by vision_tool (includes PixelSpacing,
    InstanceNumber, PatientID — unlike src/pipelines/dicom_utils.read_dicom_metadata
    which is Dataset-level only).

    Args:
        path: Path to a .dcm file.

    Returns:
        Dict with keys:
            PatientID (str), StudyDate (ISO str | None), Modality (str),
            PixelSpacing (list[float, float] | None), InstanceNumber (int | None),
            SeriesInstanceUID (str), StudyInstanceUID (str).
    """
    import pydicom  # late import — module usable without pydicom installed

    ds = pydicom.dcmread(str(path), stop_before_pixels=True)

    pixel_spacing: list[float] | None = None
    try:
        ps = getattr(ds, "PixelSpacing", None)
        if ps is not None and len(ps) >= 2:
            pixel_spacing = [float(ps[0]), float(ps[1])]
    except Exception:
        pass

    instance_number: int | None = None
    try:
        raw = getattr(ds, "InstanceNumber", None)
        instance_number = int(raw) if raw is not None else None
    except (ValueError, TypeError):
        pass

    return {
        "PatientID":         _str_tag(ds, "PatientID"),
        "StudyDate":         _parse_dicom_date(_str_tag(ds, "StudyDate")),
        "Modality":          _str_tag(ds, "Modality"),
        "PixelSpacing":      pixel_spacing,
        "InstanceNumber":    instance_number,
        "SeriesInstanceUID": _str_tag(ds, "SeriesInstanceUID"),
        "StudyInstanceUID":  _str_tag(ds, "StudyInstanceUID"),
    }


def show_dicom(path: str | Path) -> dict[str, Any]:
    """Extract and print metadata from a DICOM file (server-side, no plotting).

    This is the server-safe equivalent of show_dicom() in WELCOME.ipynb.
    Prints the main metadata fields and returns the metadata dict.

    Args:
        path: Path to a .dcm file.
    """
    meta = read_dicom_metadata(path)
    print(f"  PatientID    : {meta['PatientID'] or '—'}")
    print(f"  Modality     : {meta['Modality'] or '—'}")
    print(f"  StudyDate    : {meta['StudyDate'] or '—'}")
    print(f"  PixelSpacing : {meta['PixelSpacing']}")
    print(f"  Instance #   : {meta['InstanceNumber']}")
    suid = meta["SeriesInstanceUID"]
    print(f"  SeriesUID    : {suid[:20] + '…' if len(suid) > 20 else suid or '—'}")
    return meta
