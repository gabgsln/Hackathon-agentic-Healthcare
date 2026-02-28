"""Deterministic analysis layer — computes lesion deltas and overall status.

Applies RECIST-like rules (no LLM involved):
- progression : any lesion increases >= 20% AND >= 5 mm
- response    : any lesion decreases >= 30%
- stable      : otherwise

Usage (CLI):
    python -m src.pipelines.compute_analysis \\
        --timeline data/processed/CASE_01_timeline.json \\
        --out      data/processed/CASE_01_analysis.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
PROGRESSION_PCT_THRESHOLD: float = 20.0   # >= 20 % increase
PROGRESSION_ABS_THRESHOLD: float = 5.0    # >= 5 mm  increase (both must hold)
RESPONSE_PCT_THRESHOLD: float = 30.0      # >= 30 % decrease


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _lesion_status(delta_mm: float | None, delta_pct: float | None) -> str:
    """Classify a single lesion comparison."""
    if delta_mm is None or delta_pct is None:
        return "new"
    if delta_mm >= PROGRESSION_ABS_THRESHOLD and delta_pct >= PROGRESSION_PCT_THRESHOLD:
        return "progression"
    if delta_pct <= -RESPONSE_PCT_THRESHOLD:
        return "response"
    return "stable"


def compute_lesion_deltas(
    baseline_sizes: list[float],
    last_sizes: list[float],
) -> list[dict[str, Any]]:
    """Compare baseline vs last exam lesion sizes element-wise (sorted lists).

    When counts differ, extra last-exam lesions are marked "new"; lesions
    that vanished are marked accordingly.
    """
    n = max(len(baseline_sizes), len(last_sizes))
    deltas: list[dict[str, Any]] = []

    for i in range(n):
        has_baseline = i < len(baseline_sizes)
        has_last = i < len(last_sizes)

        b: float | None = baseline_sizes[i] if has_baseline else None
        l: float | None = last_sizes[i] if has_last else None

        if b is not None and l is not None:
            delta_mm: float | None = round(l - b, 2)
            delta_pct: float | None = round((l - b) / b * 100, 1) if b > 0 else None
        else:
            delta_mm = None
            delta_pct = None

        entry: dict[str, Any] = {
            "lesion_index": i,
            "baseline_mm": b,
            "last_mm": l,
            "delta_mm": delta_mm,
            "delta_pct": delta_pct,
            "status": _lesion_status(delta_mm, delta_pct),
        }
        if b is None:
            entry["note"] = "new lesion — absent at baseline"
        if l is None:
            entry["note"] = "lesion absent at last exam"

        deltas.append(entry)

    return deltas


def determine_overall_status(
    deltas: list[dict[str, Any]],
) -> tuple[str, list[int], list[int], str]:
    """Return (status, progression_indices, response_indices, rule_text)."""
    if not deltas:
        return (
            "unknown",
            [],
            [],
            "unknown: no lesion measurements available for comparison",
        )

    prog_idx = [d["lesion_index"] for d in deltas if d["status"] == "progression"]
    resp_idx = [d["lesion_index"] for d in deltas if d["status"] == "response"]

    if prog_idx:
        rule = (
            f"progression: lesion(s) {prog_idx} increased "
            f">= {PROGRESSION_PCT_THRESHOLD}% AND >= {PROGRESSION_ABS_THRESHOLD} mm"
        )
        return "progression", prog_idx, resp_idx, rule

    if resp_idx:
        rule = (
            f"response: lesion(s) {resp_idx} decreased >= {RESPONSE_PCT_THRESHOLD}%"
        )
        return "response", prog_idx, resp_idx, rule

    return (
        "stable",
        [],
        [],
        "stable: no progression or response criteria met",
    )


def _days_between(d1: str | None, d2: str | None) -> int | None:
    """Return integer day count between two ISO-8601 date strings, or None."""
    if not d1 or not d2:
        return None
    try:
        return (date.fromisoformat(d2) - date.fromisoformat(d1)).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# KPI helpers
# ---------------------------------------------------------------------------

def compute_sum_diameters(sizes: list[float]) -> float | None:
    """Sum of all lesion diameters. Returns None for an empty list."""
    return round(sum(sizes), 2) if sizes else None


def compute_dominant_lesion(sizes: list[float]) -> float | None:
    """Largest lesion diameter (target lesion). Returns None for an empty list."""
    return max(sizes) if sizes else None


def _pct_delta(baseline: float | None, current: float | None) -> float | None:
    """Percent change from baseline to current. Returns None on missing data or zero baseline."""
    if baseline is None or current is None or baseline == 0:
        return None
    return round((current - baseline) / baseline * 100, 1)


def compute_growth_rate(
    dom_baseline: float | None,
    dom_current: float | None,
    time_delta_days: int | None,
) -> float | None:
    """Growth rate of the dominant lesion in mm/day.

    Returns None when dominant sizes or time span are unavailable,
    or when ``time_delta_days`` is zero (same-day exams).
    """
    if dom_baseline is None or dom_current is None or not time_delta_days:
        return None
    return round((dom_current - dom_baseline) / time_delta_days, 4)


def compute_data_completeness_score(timeline: list[dict[str, Any]]) -> float:
    """Score 0–100 measuring how complete the timeline data is.

    For every exam three criteria are checked (each worth 1 point):
    1. ``study_date`` is present and non-null.
    2. ``lesion_sizes_mm`` is a non-empty list.
    3. ``report_sections`` contains at least one non-null, non-empty value.

    Score = (total points) / (n_exams × 3) × 100, rounded to 1 decimal.
    Returns 0.0 for an empty timeline.
    """
    if not timeline:
        return 0.0
    total = 0
    for exam in timeline:
        if exam.get("study_date"):
            total += 1
        if exam.get("lesion_sizes_mm"):
            total += 1
        sections = exam.get("report_sections") or {}
        if any(v for v in sections.values() if v):
            total += 1
    return round(total / (len(timeline) * 3) * 100, 1)


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def compute_analysis(
    timeline: list[dict[str, Any]],
    case_id: str,
) -> dict[str, Any]:
    """Run the full deterministic analysis on a timeline.

    Args:
        timeline: Loaded list from *_timeline.json*.
        case_id:  Identifier echoed into the output.

    Returns:
        Analysis dict ready to be serialised to *_analysis.json*.
    """
    # Extract patient_id from first record that has one
    patient_id = next(
        (e.get("patient_id", "") for e in timeline if e.get("patient_id")), ""
    )

    # Find baseline = first exam with non-empty lesion sizes
    baseline_exam: dict[str, Any] | None = None
    baseline_idx: int = -1
    for i, exam in enumerate(timeline):
        if exam.get("lesion_sizes_mm"):
            baseline_exam = exam
            baseline_idx = i
            break

    # Find last = last exam with non-empty lesion sizes
    last_exam: dict[str, Any] | None = None
    last_idx: int = -1
    for i, exam in reversed(list(enumerate(timeline))):
        if exam.get("lesion_sizes_mm"):
            last_exam = exam
            last_idx = i
            break

    # Dates summary (across all exams, not just those with lesions)
    all_dates = [e["study_date"] for e in timeline if e.get("study_date")]
    first_exam_date: str | None = all_dates[0] if all_dates else None
    last_exam_date: str | None = all_dates[-1] if all_dates else None
    time_delta_days = _days_between(first_exam_date, last_exam_date)

    # Can we compare?
    if baseline_exam is None or last_exam is None or baseline_idx == last_idx:
        deltas: list[dict[str, Any]] = []
        status = "unknown"
        prog_idx: list[int] = []
        resp_idx: list[int] = []
        rule = "unknown: fewer than two exams have lesion measurements"
    else:
        deltas = compute_lesion_deltas(
            baseline_exam["lesion_sizes_mm"],
            last_exam["lesion_sizes_mm"],
        )
        status, prog_idx, resp_idx, rule = determine_overall_status(deltas)

    baseline_sizes = baseline_exam["lesion_sizes_mm"] if baseline_exam else []
    last_sizes = last_exam["lesion_sizes_mm"] if last_exam else []

    sum_base = compute_sum_diameters(baseline_sizes)
    sum_curr = compute_sum_diameters(last_sizes)
    dom_base = compute_dominant_lesion(baseline_sizes)
    dom_curr = compute_dominant_lesion(last_sizes)

    return {
        "case_id": case_id,
        "patient_id": patient_id,
        "exam_count": len(timeline),
        "first_exam_date": first_exam_date,
        "last_exam_date": last_exam_date,
        "time_delta_days": time_delta_days,
        "baseline_exam": {
            "index": baseline_idx,
            "date": baseline_exam["study_date"] if baseline_exam else None,
            "lesion_sizes_mm": baseline_sizes,
            "accession_number": baseline_exam.get("accession_number", "") if baseline_exam else "",
        },
        "last_exam": {
            "index": last_idx,
            "date": last_exam["study_date"] if last_exam else None,
            "lesion_sizes_mm": last_sizes,
            "accession_number": last_exam.get("accession_number", "") if last_exam else "",
        },
        "lesion_deltas": deltas,
        "overall_status": status,
        "evidence": {
            "progression_triggers": prog_idx,
            "response_triggers": resp_idx,
            "rule_applied": rule,
            "thresholds": {
                "progression_pct": PROGRESSION_PCT_THRESHOLD,
                "progression_abs_mm": PROGRESSION_ABS_THRESHOLD,
                "response_pct": RESPONSE_PCT_THRESHOLD,
            },
        },
        "kpi": {
            "sum_diameters_baseline_mm":  sum_base,
            "sum_diameters_current_mm":   sum_curr,
            "sum_diameters_delta_pct":    _pct_delta(sum_base, sum_curr),
            "dominant_lesion_baseline_mm": dom_base,
            "dominant_lesion_current_mm":  dom_curr,
            "dominant_lesion_delta_pct":   _pct_delta(dom_base, dom_curr),
            "lesion_count_baseline":  len(baseline_sizes),
            "lesion_count_current":   len(last_sizes),
            "lesion_count_delta":     len(last_sizes) - len(baseline_sizes),
            "growth_rate_mm_per_day": compute_growth_rate(dom_base, dom_curr, time_delta_days),
            "data_completeness_score": compute_data_completeness_score(timeline),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.pipelines.compute_analysis",
        description="Run deterministic lesion analysis on a timeline JSON.",
    )
    p.add_argument(
        "--timeline", required=True, type=Path,
        help="Path to *_timeline.json produced by ingest_excel.",
    )
    p.add_argument(
        "--out", default=None, type=Path,
        help="Output path (default: same dir, replacing _timeline with _analysis).",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    timeline_path = Path(args.timeline)
    if not timeline_path.exists():
        print(f"[compute_analysis] ERROR: file not found: {timeline_path}", file=sys.stderr)
        sys.exit(1)

    # Derive case_id from filename (e.g. CASE_01_timeline.json → CASE_01)
    stem = timeline_path.stem  # e.g. CASE_01_timeline
    case_id = stem.replace("_timeline", "")

    timeline: list[dict] = json.loads(timeline_path.read_text(encoding="utf-8"))
    print(f"[compute_analysis] Loaded {len(timeline)} exam(s) from {timeline_path}")

    analysis = compute_analysis(timeline, case_id)

    out_path = args.out or timeline_path.parent / f"{case_id}_analysis.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[compute_analysis] Status={analysis['overall_status']}  "
        f"deltas={len(analysis['lesion_deltas'])}  → {out_path}"
    )


if __name__ == "__main__":
    main()
