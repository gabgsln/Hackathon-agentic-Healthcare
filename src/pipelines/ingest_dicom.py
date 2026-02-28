"""DICOM enrichment — match exams in a timeline JSON to a DICOM directory by AccessionNumber.

Adds a ``dicom`` field to each exam (null when no match is found).
Metadata only — no pixel data is loaded.

Usage (CLI):
    python -m src.pipelines.ingest_dicom \\
        --timeline  data/processed/CASE_01_timeline.json \\
        --dicom-dir /path/to/dicom_root \\
        --out       data/processed/CASE_01_timeline_enriched.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.pipelines.dicom_utils import (
    build_study_summary,
    group_by_accession,
    scan_dicom_dir,
)


def enrich_timeline(
    timeline: list[dict[str, Any]],
    dicom_dir: Path,
) -> list[dict[str, Any]]:
    """Enrich each exam in *timeline* with DICOM study metadata.

    Matching is done by ``accession_number`` (case-sensitive string comparison).
    Exams without a match get ``"dicom": null``.

    Args:
        timeline:  Loaded list from *_timeline.json*.
        dicom_dir: Root directory to scan for DICOM files.

    Returns:
        New list of enriched exam dicts (original dicts are not mutated).
    """
    print(f"[ingest_dicom] Scanning {dicom_dir} ...")
    records = scan_dicom_dir(dicom_dir)
    print(f"[ingest_dicom] Found {len(records)} DICOM file(s).")

    accession_index = group_by_accession(records)
    print(
        f"[ingest_dicom] Unique AccessionNumbers in DICOM dir: {len(accession_index)}"
    )

    enriched: list[dict[str, Any]] = []
    matched = 0

    for exam in timeline:
        acc = exam.get("accession_number", "")
        dicom_files = accession_index.get(acc)

        if dicom_files:
            summary = build_study_summary(dicom_files)
            matched += 1
        else:
            summary = None

        enriched.append({**exam, "dicom": summary})

    print(
        f"[ingest_dicom] Matched {matched}/{len(timeline)} exam(s) to DICOM studies."
    )
    return enriched


def ingest_dicom(
    timeline_path: Path,
    dicom_dir: Path,
    out_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load, enrich, and write the enriched timeline.

    Args:
        timeline_path: Path to *_timeline.json*.
        dicom_dir:     Root directory containing DICOM files.
        out_path:      Override output path.
                       Defaults to same dir as timeline, with ``_enriched`` suffix.

    Returns:
        Enriched list of exam dicts.
    """
    timeline_path = Path(timeline_path)
    if not timeline_path.exists():
        raise FileNotFoundError(f"Timeline not found: {timeline_path}")
    if not dicom_dir.exists():
        raise FileNotFoundError(f"DICOM directory not found: {dicom_dir}")

    timeline: list[dict] = json.loads(timeline_path.read_text(encoding="utf-8"))
    enriched = enrich_timeline(timeline, dicom_dir)

    if out_path is None:
        stem = timeline_path.stem  # e.g. CASE_01_timeline
        out_path = timeline_path.parent / f"{stem}_enriched.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ingest_dicom] Written → {out_path}")
    return enriched


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.pipelines.ingest_dicom",
        description="Enrich a timeline JSON with DICOM study metadata (by AccessionNumber).",
    )
    p.add_argument("--timeline",  required=True, type=Path, help="*_timeline.json path.")
    p.add_argument("--dicom-dir", required=True, type=Path, dest="dicom_dir",
                   help="Root directory containing DICOM files.")
    p.add_argument("--out",       default=None,  type=Path,
                   help="Output path (default: *_timeline_enriched.json).")
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    try:
        ingest_dicom(
            timeline_path=args.timeline,
            dicom_dir=args.dicom_dir,
            out_path=args.out,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ingest_dicom] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
