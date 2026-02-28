"""Low-level DICOM utilities — metadata only, no pixel loading.

All functions work on pydicom.Dataset objects so they are easily
unit-testable without real DICOM files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _str_tag(ds: Any, tag: str, default: str = "") -> str:
    """Safely read a DICOM tag as a stripped string."""
    try:
        val = getattr(ds, tag, None)
        if val is None:
            return default
        return str(val).strip()
    except Exception:
        return default


def _int_tag(ds: Any, tag: str) -> int | None:
    """Safely read a DICOM tag as int."""
    try:
        val = getattr(ds, tag, None)
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def parse_dicom_date(raw: str) -> str | None:
    """Convert DICOM date format YYYYMMDD → ISO YYYY-MM-DD.

    Returns None for empty or malformed values.
    """
    s = raw.strip() if raw else ""
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def read_dicom_metadata(ds: Any) -> dict[str, Any]:
    """Extract a structured metadata dict from a pydicom Dataset.

    Args:
        ds: A ``pydicom.Dataset`` (loaded with ``stop_before_pixels=True``).

    Returns:
        Dict with the following keys:

        - ``accession_number``   str
        - ``study_instance_uid`` str
        - ``series_instance_uid``str
        - ``study_date``         str | None  (ISO format)
        - ``modality``           str
        - ``series_description`` str
        - ``series_number``      int | None
    """
    return {
        "accession_number":    _str_tag(ds, "AccessionNumber"),
        "study_instance_uid":  _str_tag(ds, "StudyInstanceUID"),
        "series_instance_uid": _str_tag(ds, "SeriesInstanceUID"),
        "study_date":          parse_dicom_date(_str_tag(ds, "StudyDate")),
        "modality":            _str_tag(ds, "Modality"),
        "series_description":  _str_tag(ds, "SeriesDescription"),
        "series_number":       _int_tag(ds, "SeriesNumber"),
    }


def scan_dicom_dir(dicom_dir: Path) -> list[dict[str, Any]]:
    """Recursively scan *dicom_dir* and return metadata for every DICOM file found.

    Only files that can be read by pydicom are included; others are silently
    skipped. Pixel data is never loaded (``stop_before_pixels=True``).

    Args:
        dicom_dir: Root directory to scan.

    Returns:
        List of metadata dicts (one per file).
    """
    import pydicom  # import here so the module is importable without pydicom

    records: list[dict[str, Any]] = []
    patterns = ("**/*.dcm", "**/*.DCM", "**/*")  # some DICOMs have no extension

    seen: set[Path] = set()
    for pattern in patterns:
        for fpath in dicom_dir.glob(pattern):
            if not fpath.is_file() or fpath in seen:
                continue
            seen.add(fpath)
            try:
                ds = pydicom.dcmread(str(fpath), stop_before_pixels=True, force=False)
                meta = read_dicom_metadata(ds)
                meta["file_path"] = str(fpath)
                records.append(meta)
            except Exception:
                pass  # skip non-DICOM files silently

    return records


def group_by_accession(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group metadata records by AccessionNumber.

    Records without an AccessionNumber are placed under the key ``""``.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        key = rec.get("accession_number", "") or ""
        groups.setdefault(key, []).append(rec)
    return groups


def build_study_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of per-file records sharing the same AccessionNumber
    into a study-level summary.

    Returns a dict with:
    - ``study_instance_uid``  str
    - ``study_date``          str | None
    - ``ct_series_uid``       str | None  (first CT series found)
    - ``seg_series_uid``      str | None  (first SEG series found)
    - ``series``              list of series-level dicts
    """
    if not records:
        return {}

    # Pick study-level fields from first record (they should be identical)
    study_uid = next(
        (r["study_instance_uid"] for r in records if r.get("study_instance_uid")), ""
    )
    study_date = next(
        (r["study_date"] for r in records if r.get("study_date")), None
    )

    # Group by series
    series_map: dict[str, list[dict]] = {}
    for r in records:
        sid = r.get("series_instance_uid", "")
        series_map.setdefault(sid, []).append(r)

    series_list: list[dict[str, Any]] = []
    for sid, files in series_map.items():
        first = files[0]
        series_list.append({
            "series_instance_uid": sid,
            "modality": first.get("modality", ""),
            "series_description": first.get("series_description", ""),
            "series_number": first.get("series_number"),
            "file_count": len(files),
        })

    # Sort series by series_number (None last)
    series_list.sort(
        key=lambda s: (s["series_number"] is None, s["series_number"] or 0)
    )

    ct_series_uid = next(
        (s["series_instance_uid"] for s in series_list if s["modality"] == "CT"), None
    )
    seg_series_uid = next(
        (s["series_instance_uid"] for s in series_list if s["modality"] == "SEG"), None
    )

    return {
        "study_instance_uid": study_uid,
        "study_date": study_date,
        "ct_series_uid": ct_series_uid,
        "seg_series_uid": seg_series_uid,
        "series": series_list,
    }
