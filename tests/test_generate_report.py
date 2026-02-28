"""Sanity tests for the deterministic report renderer."""

from src.pipelines.generate_report import build_context, render_report

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TIMELINE_FULL = [
    {
        "patient_id": "P001",
        "accession_number": "ACC001",
        "study_date": "2024-01-01",
        "lesion_sizes_mm": [10.0],
        "report_raw": "CLINICAL INFORMATION. Nodule suivi.",
        "report_sections": {
            "clinical_information": "Nodule suivi.",
            "study_technique": "CT thorax sans injection.",
            "report": "Nodule LSD 10mm.",
            "conclusions": "Stable par rapport au précédent.",
        },
    },
    {
        "patient_id": "P001",
        "accession_number": "ACC002",
        "study_date": "2025-01-01",
        "lesion_sizes_mm": [16.0],
        "report_raw": "CLINICAL INFORMATION. Contrôle. CONCLUSIONS. Progression.",
        "report_sections": {
            "clinical_information": "Contrôle à 12 mois.",
            "study_technique": None,
            "report": None,
            "conclusions": "Progression du nodule LSD.",
        },
    },
]

ANALYSIS_PROGRESSION = {
    "case_id": "CASE_01",
    "patient_id": "P001",
    "exam_count": 2,
    "first_exam_date": "2024-01-01",
    "last_exam_date": "2025-01-01",
    "time_delta_days": 366,
    "baseline_exam": {"index": 0, "date": "2024-01-01", "lesion_sizes_mm": [10.0], "accession_number": "ACC001"},
    "last_exam": {"index": 1, "date": "2025-01-01", "lesion_sizes_mm": [16.0], "accession_number": "ACC002"},
    "lesion_deltas": [
        {"lesion_index": 0, "baseline_mm": 10.0, "last_mm": 16.0, "delta_mm": 6.0, "delta_pct": 60.0, "status": "progression"},
    ],
    "overall_status": "progression",
    "evidence": {
        "progression_triggers": [0],
        "response_triggers": [],
        "rule_applied": "progression: lesion(s) [0] increased >= 20.0% AND >= 5.0 mm",
        "thresholds": {"progression_pct": 20.0, "progression_abs_mm": 5.0, "response_pct": 30.0},
    },
}

ANALYSIS_STABLE = {
    **ANALYSIS_PROGRESSION,
    "overall_status": "stable",
    "lesion_deltas": [
        {"lesion_index": 0, "baseline_mm": 10.0, "last_mm": 11.0, "delta_mm": 1.0, "delta_pct": 10.0, "status": "stable"},
    ],
    "evidence": {
        "progression_triggers": [],
        "response_triggers": [],
        "rule_applied": "stable: no progression or response criteria met",
        "thresholds": {"progression_pct": 20.0, "progression_abs_mm": 5.0, "response_pct": 30.0},
    },
}

ANALYSIS_UNKNOWN = {
    **ANALYSIS_PROGRESSION,
    "overall_status": "unknown",
    "lesion_deltas": [],
    "evidence": {
        "progression_triggers": [],
        "response_triggers": [],
        "rule_applied": "unknown: fewer than two exams have lesion measurements",
        "thresholds": {"progression_pct": 20.0, "progression_abs_mm": 5.0, "response_pct": 30.0},
    },
}


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_patient_id_propagated(self):
        ctx = build_context(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert ctx["patient_id"] == "P001"

    def test_exam_count(self):
        ctx = build_context(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert ctx["exam_count"] == 2

    def test_latest_sections_from_last_exam(self):
        ctx = build_context(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert ctx["latest_clinical_information"] == "Contrôle à 12 mois."
        assert ctx["latest_conclusions"] == "Progression du nodule LSD."

    def test_fallback_to_earlier_exam_for_missing_section(self):
        # latest_study_technique is None in exam 2, should fall back to exam 1
        ctx = build_context(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert ctx["latest_study_technique"] == "CT thorax sans injection."

    def test_time_delta_days(self):
        ctx = build_context(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert ctx["time_delta_days"] == 366

    def test_overall_status(self):
        ctx = build_context(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert ctx["overall_status"] == "progression"

    def test_generated_at_present(self):
        ctx = build_context(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert ctx["generated_at"]  # non-empty string


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------

class TestRenderReport:
    def test_output_is_string(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert isinstance(md, str)
        assert len(md) > 100

    def test_contains_patient_id(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert "P001" in md

    def test_contains_overall_status(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert "PROGRESSION" in md

    def test_stable_status_rendered(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_STABLE)
        assert "STABLE" in md

    def test_unknown_status_rendered(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_UNKNOWN)
        assert "UNKNOWN" in md

    def test_lesion_delta_table_present(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert "16.0" in md   # last_mm
        assert "6.0" in md    # delta_mm

    def test_latest_clinical_info_in_output(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert "Contrôle à 12 mois." in md

    def test_recommendations_section_present(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert "Recommandations" in md

    def test_tracability_rule_applied(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert "progression" in md.lower()

    def test_progression_recommendations_content(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_PROGRESSION)
        assert "oncologique" in md.lower() or "4 semaines" in md

    def test_stable_recommendations_content(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_STABLE)
        assert "3" in md  # "3–6 mois"

    def test_response_recommendations_content(self):
        analysis_resp = {
            **ANALYSIS_PROGRESSION,
            "overall_status": "response",
            "lesion_deltas": [
                {"lesion_index": 0, "baseline_mm": 20.0, "last_mm": 12.0,
                 "delta_mm": -8.0, "delta_pct": -40.0, "status": "response"},
            ],
            "evidence": {
                **ANALYSIS_PROGRESSION["evidence"],
                "rule_applied": "response: ...",
                "progression_triggers": [],
                "response_triggers": [0],
            },
        }
        md = render_report(TIMELINE_FULL, analysis_resp)
        assert "RESPONSE" in md

    def test_no_lesion_deltas_shows_placeholder(self):
        md = render_report(TIMELINE_FULL, ANALYSIS_UNKNOWN)
        assert "Aucun delta" in md or "Aucune mesure" in md

    def test_empty_timeline_does_not_crash(self):
        md = render_report([], ANALYSIS_UNKNOWN)
        assert isinstance(md, str)
