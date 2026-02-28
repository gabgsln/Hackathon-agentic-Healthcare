"""Parse patient Excel files into structured timeline JSON.

Usage (CLI):
    python -m src.pipelines.ingest_excel \\
        --excel data/raw/case01.xlsx \\
        --case-id CASE_01 \\
        [--sheet "Sheet1"] \\
        [--out data/processed/CASE_01_timeline.json]

Output schema (one object per row / exam):
    {
        "patient_id": str,
        "accession_number": str,
        "study_date": "YYYY-MM-DD" | null,
        "lesion_sizes_mm": [float, ...],
        "report_raw": str,
        "report_sections": {
            "clinical_information": str | null,
            "study_technique": str | null,
            "report": str | null,
            "conclusions": str | null
        }
    }
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from src.pipelines.parsers import parse_lesion_sizes, split_report_sections


# ---------------------------------------------------------------------------
# Column discovery helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Lowercase and strip all separators for fuzzy column matching."""
    return s.lower().replace(" ", "").replace("_", "").replace("/", "").replace("-", "")


def _find_col(columns: list[str], *keywords: str) -> str | None:
    """Return the first column whose normalised name contains any keyword."""
    for col in columns:
        col_n = _norm(col)
        for kw in keywords:
            if kw in col_n:
                return col
    return None


def _find_all_cols(columns: list[str], *keywords: str) -> list[str]:
    """Return ALL columns whose normalised name contains any keyword."""
    seen: set[str] = set()
    result: list[str] = []
    for col in columns:
        col_n = _norm(col)
        for kw in keywords:
            if kw in col_n and col not in seen:
                result.append(col)
                seen.add(col)
                break
    return result


# ---------------------------------------------------------------------------
# Value coercion helpers
# ---------------------------------------------------------------------------

def _to_str(val: Any) -> str:
    """Convert a cell value to a string; return '' for NaN / None."""
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip()


def _to_accession_str(val: Any) -> str:
    """Convert AccessionNumber to string, always without a trailing '.0'.

    Excel stores some accession numbers as numerics. pandas reads them as
    '123456.0' with dtype=str. This strips the fractional part when the value
    represents a whole number (e.g. '123456.0' → '123456').
    """
    s = _to_str(val)
    # Remove trailing '.0' produced when Excel stores the value as a float
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        return s[:-2]
    return s


def _to_date(val: Any) -> str | None:
    """Parse any date-like value to ISO-8601 string; return None on failure."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    try:
        return pd.to_datetime(val).strftime("%Y-%m-%d")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core ingestion logic
# ---------------------------------------------------------------------------

def _discover_columns(df: pd.DataFrame) -> dict[str, Any]:
    """Map semantic roles to actual DataFrame column names."""
    cols = list(df.columns)
    return {
        "patient_id":        _find_col(cols, "patientid", "patient"),
        "accession_number":  _find_col(cols, "accessionnumber", "accession"),
        "date":              _find_col(cols, "studydate", "date", "datum"),
        # All lesion-size columns (there may be several)
        "lesion_sizes":      _find_all_cols(cols, "lesion", "size", "mesure", "taille", "mm"),
        # Report / pseudo-report column
        "report":            _find_col(cols, "clinical", "pseudo", "report", "compte", "rendu"),
    }


def _row_to_exam(row: pd.Series, col_map: dict[str, Any]) -> dict[str, Any]:
    """Convert one DataFrame row into the target exam dict."""
    # patient_id
    pid_col = col_map["patient_id"]
    patient_id = _to_str(row[pid_col]) if pid_col else ""

    # accession_number — always a clean string, never '123.0'
    acc_col = col_map["accession_number"]
    accession_number = _to_accession_str(row[acc_col]) if acc_col else ""

    # study_date
    date_col = col_map["date"]
    study_date = _to_date(row[date_col]) if date_col else None

    # lesion sizes — collect from all matching columns, flatten, deduplicate
    raw_sizes: list[float] = []
    for lc in col_map["lesion_sizes"]:
        raw_sizes.extend(parse_lesion_sizes(row[lc]))
    lesion_sizes = sorted(set(raw_sizes))

    # raw report text
    rep_col = col_map["report"]
    report_raw = _to_str(row[rep_col]) if rep_col else ""

    # parsed report sections
    report_sections = split_report_sections(report_raw)

    return {
        "patient_id":       patient_id,
        "accession_number": accession_number,
        "study_date":       study_date,
        "lesion_sizes_mm":  lesion_sizes,
        "report_raw":       report_raw,
        "report_sections":  report_sections,
    }


def ingest_excel(
    excel_path: Path,
    case_id: str,
    sheet_name: str | int | None = 0,
    out_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Parse an Excel file into a list of exam dicts and write JSON output.

    Args:
        excel_path:  Path to the ``.xlsx`` file.
        case_id:     Identifier used to name the output file.
        sheet_name:  Sheet to read (name or 0-based index). Defaults to the first sheet.
        out_path:    Override the output JSON path.
                     Defaults to ``data/processed/<case_id>_timeline.json``.

    Returns:
        List of exam dicts (also written to *out_path*).

    Raises:
        FileNotFoundError: If *excel_path* does not exist.
        ValueError: If the DataFrame is empty after loading.
    """
    excel_path = Path(excel_path)
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    print(f"[ingest_excel] Reading: {excel_path}  (sheet={sheet_name!r})")
    df = pd.read_excel(excel_path, sheet_name=sheet_name, dtype=str, engine="openpyxl")
    # Strip column names
    df.columns = [str(c).strip() for c in df.columns]
    # Drop fully empty rows and fully empty columns
    df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)

    if df.empty:
        raise ValueError(f"No data rows found in {excel_path} (sheet={sheet_name!r}).")

    print(f"[ingest_excel] Loaded {len(df)} row(s), {len(df.columns)} column(s).")
    print(f"[ingest_excel] Columns: {list(df.columns)}")

    col_map = _discover_columns(df)
    print(f"[ingest_excel] Column mapping: {col_map}")

    # Build exam list
    exams: list[dict[str, Any]] = [_row_to_exam(row, col_map) for _, row in df.iterrows()]

    # Sort by date when available; rows without dates stay in original order (appended last)
    dated   = [e for e in exams if e["study_date"] is not None]
    undated = [e for e in exams if e["study_date"] is None]
    exams = sorted(dated, key=lambda e: e["study_date"]) + undated  # type: ignore[arg-type]

    # Determine output path
    if out_path is None:
        out_dir = Path("data/processed")
        out_path = out_dir / f"{case_id}_timeline.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(json.dumps(exams, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ingest_excel] Written {len(exams)} exam(s) → {out_path}")
    return exams


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.pipelines.ingest_excel",
        description="Parse an Excel patient file into a structured timeline JSON.",
    )
    p.add_argument("--excel",   required=True, type=Path, help="Path to the .xlsx input file.")
    p.add_argument("--case-id", required=True, dest="case_id", help="Case identifier (used in output filename).")
    p.add_argument("--sheet",   default=0,     dest="sheet",   help="Sheet name or 0-based index (default: 0).")
    p.add_argument("--out",     default=None,  type=Path,      help="Override output JSON path.")
    return p


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Convert --sheet to int when it looks like a number
    sheet: str | int = args.sheet
    try:
        sheet = int(sheet)
    except (ValueError, TypeError):
        pass

    try:
        exams = ingest_excel(
            excel_path=args.excel,
            case_id=args.case_id,
            sheet_name=sheet,
            out_path=args.out,
        )
        print(f"[ingest_excel] Done — {len(exams)} exam(s) parsed.")
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ingest_excel] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
