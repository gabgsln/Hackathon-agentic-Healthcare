"""Tests for src/pipelines/compute_analysis.py — deterministic rules."""

from src.pipelines.compute_analysis import (
    PROGRESSION_PCT_THRESHOLD,
    _days_between,
    _lesion_status,
    _pct_delta,
    compute_analysis,
    compute_data_completeness_score,
    compute_dominant_lesion,
    compute_growth_rate,
    compute_lesion_deltas,
    compute_sum_diameters,
    determine_overall_status,
)

# ===========================================================================
# _lesion_status
# ===========================================================================

class TestLesionStatus:
    def test_progression_both_thresholds_met(self):
        # 10 → 15 mm = +5mm, +50%
        assert _lesion_status(5.0, 50.0) == "progression"

    def test_progression_abs_met_pct_not(self):
        # +6mm but only +10% (e.g. 60mm → 66mm) — NOT progression
        assert _lesion_status(6.0, 10.0) == "stable"

    def test_progression_pct_met_abs_not(self):
        # +50% but only +2mm (e.g. 4mm → 6mm) — NOT progression
        assert _lesion_status(2.0, 50.0) == "stable"

    def test_response(self):
        # -40% decrease
        assert _lesion_status(-8.0, -40.0) == "response"

    def test_response_boundary(self):
        # exactly -30% = response
        assert _lesion_status(-6.0, -30.0) == "response"

    def test_stable_small_increase(self):
        assert _lesion_status(1.0, 5.0) == "stable"

    def test_stable_small_decrease(self):
        assert _lesion_status(-1.0, -10.0) == "stable"

    def test_none_inputs_gives_new(self):
        assert _lesion_status(None, None) == "new"

    def test_one_none_gives_new(self):
        assert _lesion_status(5.0, None) == "new"


# ===========================================================================
# compute_lesion_deltas
# ===========================================================================

class TestComputeLesionDeltas:
    def test_basic_progression(self):
        # 10 → 16 mm = +6mm / +60%
        deltas = compute_lesion_deltas([10.0], [16.0])
        assert len(deltas) == 1
        d = deltas[0]
        assert d["lesion_index"] == 0
        assert d["baseline_mm"] == 10.0
        assert d["last_mm"] == 16.0
        assert d["delta_mm"] == 6.0
        assert d["delta_pct"] == 60.0
        assert d["status"] == "progression"

    def test_basic_response(self):
        # 20 → 12 mm = -8mm / -40%
        deltas = compute_lesion_deltas([20.0], [12.0])
        assert deltas[0]["status"] == "response"
        assert deltas[0]["delta_pct"] == -40.0

    def test_stable(self):
        deltas = compute_lesion_deltas([15.0], [15.5])
        assert deltas[0]["status"] == "stable"

    def test_multiple_lesions(self):
        # Two lesions: first stable, second progressing
        deltas = compute_lesion_deltas([10.0, 8.0], [11.0, 15.0])
        assert deltas[0]["status"] == "stable"
        assert deltas[1]["status"] == "progression"

    def test_new_lesion_in_last_exam(self):
        # Baseline has 1, last has 2
        deltas = compute_lesion_deltas([10.0], [10.5, 8.0])
        assert len(deltas) == 2
        assert deltas[1]["baseline_mm"] is None
        assert deltas[1]["status"] == "new"
        assert "note" in deltas[1]

    def test_lesion_absent_in_last_exam(self):
        deltas = compute_lesion_deltas([10.0, 8.0], [10.5])
        assert len(deltas) == 2
        assert deltas[1]["last_mm"] is None

    def test_empty_both(self):
        assert compute_lesion_deltas([], []) == []

    def test_delta_rounding(self):
        deltas = compute_lesion_deltas([3.0], [6.0])
        assert isinstance(deltas[0]["delta_mm"], float)
        assert isinstance(deltas[0]["delta_pct"], float)


# ===========================================================================
# determine_overall_status
# ===========================================================================

class TestDetermineOverallStatus:
    def test_progression_wins(self):
        deltas = compute_lesion_deltas([10.0, 20.0], [18.0, 10.0])
        # 10→18: +8mm/+80% = progression; 20→10: -50% = response
        # progression should win
        status, prog, resp, rule = determine_overall_status(deltas)
        assert status == "progression"
        assert 0 in prog

    def test_response_when_no_progression(self):
        deltas = compute_lesion_deltas([20.0], [12.0])
        status, _, resp, _ = determine_overall_status(deltas)
        assert status == "response"
        assert 0 in resp

    def test_stable(self):
        deltas = compute_lesion_deltas([10.0], [10.5])
        status, prog, resp, _ = determine_overall_status(deltas)
        assert status == "stable"
        assert prog == []
        assert resp == []

    def test_empty_deltas_gives_unknown(self):
        status, _, _, rule = determine_overall_status([])
        assert status == "unknown"
        assert "unknown" in rule

    def test_rule_text_contains_threshold(self):
        deltas = compute_lesion_deltas([10.0], [16.0])
        _, _, _, rule = determine_overall_status(deltas)
        assert str(int(PROGRESSION_PCT_THRESHOLD)) in rule or str(PROGRESSION_PCT_THRESHOLD) in rule


# ===========================================================================
# _days_between
# ===========================================================================

class TestDaysBetween:
    def test_basic(self):
        assert _days_between("2024-01-01", "2025-01-01") == 366  # 2024 is a leap year

    def test_same_date(self):
        assert _days_between("2024-06-15", "2024-06-15") == 0

    def test_none_inputs(self):
        assert _days_between(None, "2024-01-01") is None
        assert _days_between("2024-01-01", None) is None
        assert _days_between(None, None) is None

    def test_invalid_date(self):
        assert _days_between("not-a-date", "2024-01-01") is None


# ===========================================================================
# compute_analysis (integration)
# ===========================================================================

TIMELINE_TWO_EXAMS = [
    {
        "patient_id": "P001",
        "accession_number": "ACC001",
        "study_date": "2024-01-01",
        "lesion_sizes_mm": [10.0, 8.0],
        "report_raw": "",
        "report_sections": {},
    },
    {
        "patient_id": "P001",
        "accession_number": "ACC002",
        "study_date": "2024-07-01",
        "lesion_sizes_mm": [18.0, 7.5],
        "report_raw": "",
        "report_sections": {},
    },
]

TIMELINE_NO_LESIONS = [
    {
        "patient_id": "P002",
        "accession_number": "ACC010",
        "study_date": "2024-01-01",
        "lesion_sizes_mm": [],
        "report_raw": "",
        "report_sections": {},
    },
]


class TestComputeAnalysis:
    def test_basic_structure(self):
        result = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_01")
        assert result["case_id"] == "CASE_01"
        assert result["patient_id"] == "P001"
        assert result["exam_count"] == 2
        assert "overall_status" in result
        assert "lesion_deltas" in result
        assert "evidence" in result
        assert "thresholds" in result["evidence"]

    def test_progression_detected(self):
        # 10→18 mm = +8mm +80% ⇒ progression
        result = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_01")
        assert result["overall_status"] == "progression"

    def test_time_delta_computed(self):
        result = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_01")
        assert result["time_delta_days"] == 182  # 2024-01-01 → 2024-07-01

    def test_baseline_and_last_exam_fields(self):
        result = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_01")
        assert result["baseline_exam"]["accession_number"] == "ACC001"
        assert result["last_exam"]["accession_number"] == "ACC002"

    def test_no_lesions_gives_unknown(self):
        result = compute_analysis(TIMELINE_NO_LESIONS, "CASE_02")
        assert result["overall_status"] == "unknown"
        assert result["lesion_deltas"] == []

    def test_single_exam_gives_unknown(self):
        timeline = [TIMELINE_TWO_EXAMS[0]]
        result = compute_analysis(timeline, "CASE_03")
        assert result["overall_status"] == "unknown"

    def test_response_case(self):
        timeline = [
            {**TIMELINE_TWO_EXAMS[0], "lesion_sizes_mm": [20.0]},
            {**TIMELINE_TWO_EXAMS[1], "lesion_sizes_mm": [12.0]},  # -40%
        ]
        result = compute_analysis(timeline, "CASE_04")
        assert result["overall_status"] == "response"

    def test_stable_case(self):
        timeline = [
            {**TIMELINE_TWO_EXAMS[0], "lesion_sizes_mm": [10.0]},
            {**TIMELINE_TWO_EXAMS[1], "lesion_sizes_mm": [11.0]},  # +10%, +1mm
        ]
        result = compute_analysis(timeline, "CASE_05")
        assert result["overall_status"] == "stable"

    def test_missing_dates_gives_null_delta(self):
        timeline = [
            {**TIMELINE_TWO_EXAMS[0], "study_date": None},
            {**TIMELINE_TWO_EXAMS[1], "study_date": None},
        ]
        result = compute_analysis(timeline, "CASE_06")
        assert result["time_delta_days"] is None
        assert result["first_exam_date"] is None


# ===========================================================================
# KPI helpers
# ===========================================================================

class TestComputeSumDiameters:
    def test_single_lesion(self):
        assert compute_sum_diameters([12.5]) == 12.5

    def test_multiple_lesions(self):
        assert compute_sum_diameters([10.0, 8.0, 5.5]) == 23.5

    def test_empty_returns_none(self):
        assert compute_sum_diameters([]) is None

    def test_result_is_rounded(self):
        result = compute_sum_diameters([10.123, 5.456])
        assert result == round(10.123 + 5.456, 2)


class TestComputeDominantLesion:
    def test_single(self):
        assert compute_dominant_lesion([12.5]) == 12.5

    def test_picks_maximum(self):
        assert compute_dominant_lesion([8.0, 14.3, 10.0]) == 14.3

    def test_empty_returns_none(self):
        assert compute_dominant_lesion([]) is None


class TestPctDelta:
    def test_increase(self):
        assert _pct_delta(10.0, 12.0) == 20.0

    def test_decrease(self):
        assert _pct_delta(20.0, 14.0) == -30.0

    def test_no_change(self):
        assert _pct_delta(10.0, 10.0) == 0.0

    def test_zero_baseline_returns_none(self):
        assert _pct_delta(0.0, 5.0) is None

    def test_none_baseline_returns_none(self):
        assert _pct_delta(None, 5.0) is None

    def test_none_current_returns_none(self):
        assert _pct_delta(10.0, None) is None

    def test_both_none_returns_none(self):
        assert _pct_delta(None, None) is None

    def test_result_rounded_to_one_decimal(self):
        # 10 → 13.333... = +33.333...%
        result = _pct_delta(10.0, 13.333)
        assert result == round((13.333 - 10.0) / 10.0 * 100, 1)


class TestComputeGrowthRate:
    def test_basic(self):
        # +5mm over 100 days = 0.05 mm/day
        assert compute_growth_rate(10.0, 15.0, 100) == 0.05

    def test_negative_growth(self):
        # -4mm over 200 days
        assert compute_growth_rate(20.0, 16.0, 200) == -0.02

    def test_zero_days_returns_none(self):
        assert compute_growth_rate(10.0, 15.0, 0) is None

    def test_none_days_returns_none(self):
        assert compute_growth_rate(10.0, 15.0, None) is None

    def test_none_baseline_returns_none(self):
        assert compute_growth_rate(None, 15.0, 100) is None

    def test_none_current_returns_none(self):
        assert compute_growth_rate(10.0, None, 100) is None

    def test_result_rounded_to_four_decimals(self):
        result = compute_growth_rate(10.0, 11.0, 3)
        assert result == round(1.0 / 3, 4)


class TestComputeDataCompletenessScore:
    def _exam(self, date=True, lesions=True, sections=True):
        return {
            "study_date": "2024-01-01" if date else None,
            "lesion_sizes_mm": [10.0] if lesions else [],
            "report_sections": {"clinical_information": "Info."} if sections else {},
        }

    def test_all_complete_gives_100(self):
        timeline = [self._exam(), self._exam()]
        assert compute_data_completeness_score(timeline) == 100.0

    def test_all_missing_gives_0(self):
        timeline = [self._exam(date=False, lesions=False, sections=False)] * 3
        assert compute_data_completeness_score(timeline) == 0.0

    def test_empty_timeline_gives_0(self):
        assert compute_data_completeness_score([]) == 0.0

    def test_partial_two_of_three_criteria(self):
        # date + lesions present, sections missing → 2/3 per exam
        exam = self._exam(sections=False)
        result = compute_data_completeness_score([exam])
        assert result == round(2 / 3 * 100, 1)

    def test_mixed_exams(self):
        # exam1: all 3 → 3 pts; exam2: only date → 1 pt; total=4/6
        e1 = self._exam()
        e2 = self._exam(lesions=False, sections=False)
        result = compute_data_completeness_score([e1, e2])
        assert result == round(4 / 6 * 100, 1)

    def test_single_exam_fully_complete(self):
        assert compute_data_completeness_score([self._exam()]) == 100.0

    def test_sections_with_all_none_values_counts_as_missing(self):
        exam = {
            "study_date": "2024-01-01",
            "lesion_sizes_mm": [10.0],
            "report_sections": {"clinical_information": None, "conclusions": None},
        }
        result = compute_data_completeness_score([exam])
        assert result == round(2 / 3 * 100, 1)


# ===========================================================================
# KPI integration via compute_analysis
# ===========================================================================

class TestKPIIntegration:
    def test_kpi_key_present(self):
        result = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")
        assert "kpi" in result

    def test_kpi_all_fields_present(self):
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        expected_keys = {
            "sum_diameters_baseline_mm", "sum_diameters_current_mm", "sum_diameters_delta_pct",
            "dominant_lesion_baseline_mm", "dominant_lesion_current_mm", "dominant_lesion_delta_pct",
            "lesion_count_baseline", "lesion_count_current", "lesion_count_delta",
            "growth_rate_mm_per_day", "data_completeness_score",
        }
        assert set(kpi.keys()) == expected_keys

    def test_sum_diameters_baseline(self):
        # TIMELINE_TWO_EXAMS baseline = [10.0, 8.0] → sum = 18.0
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert kpi["sum_diameters_baseline_mm"] == 18.0

    def test_sum_diameters_current(self):
        # last exam = [18.0, 7.5] → sum = 25.5
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert kpi["sum_diameters_current_mm"] == 25.5

    def test_sum_diameters_delta_pct(self):
        # 18.0 → 25.5 = +41.7%
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert kpi["sum_diameters_delta_pct"] == round((25.5 - 18.0) / 18.0 * 100, 1)

    def test_dominant_lesion_baseline(self):
        # max([10.0, 8.0]) = 10.0
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert kpi["dominant_lesion_baseline_mm"] == 10.0

    def test_dominant_lesion_current(self):
        # max([18.0, 7.5]) = 18.0
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert kpi["dominant_lesion_current_mm"] == 18.0

    def test_dominant_lesion_delta_pct(self):
        # 10.0 → 18.0 = +80%
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert kpi["dominant_lesion_delta_pct"] == 80.0

    def test_lesion_counts(self):
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert kpi["lesion_count_baseline"] == 2
        assert kpi["lesion_count_current"] == 2
        assert kpi["lesion_count_delta"] == 0

    def test_lesion_count_delta_new_lesion(self):
        timeline = [
            {**TIMELINE_TWO_EXAMS[0], "lesion_sizes_mm": [10.0]},
            {**TIMELINE_TWO_EXAMS[1], "lesion_sizes_mm": [10.5, 8.0]},
        ]
        kpi = compute_analysis(timeline, "CASE_KPI2")["kpi"]
        assert kpi["lesion_count_baseline"] == 1
        assert kpi["lesion_count_current"] == 2
        assert kpi["lesion_count_delta"] == 1

    def test_growth_rate_computed(self):
        # dominant: 10→18 over 182 days
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        expected = round((18.0 - 10.0) / 182, 4)
        assert kpi["growth_rate_mm_per_day"] == expected

    def test_growth_rate_none_when_no_dates(self):
        timeline = [
            {**TIMELINE_TWO_EXAMS[0], "study_date": None},
            {**TIMELINE_TWO_EXAMS[1], "study_date": None},
        ]
        kpi = compute_analysis(timeline, "CASE_KPI3")["kpi"]
        assert kpi["growth_rate_mm_per_day"] is None

    def test_kpi_none_when_single_exam(self):
        timeline = [TIMELINE_TWO_EXAMS[0]]
        kpi = compute_analysis(timeline, "CASE_KPI4")["kpi"]
        # Baseline fills from the single exam, last is same exam → no comparison
        # but sum/dominant are still computed from that exam's sizes
        assert kpi["sum_diameters_baseline_mm"] == 18.0
        assert kpi["sum_diameters_current_mm"] == 18.0

    def test_kpi_none_when_no_lesions(self):
        kpi = compute_analysis(TIMELINE_NO_LESIONS, "CASE_KPI5")["kpi"]
        assert kpi["sum_diameters_baseline_mm"] is None
        assert kpi["dominant_lesion_baseline_mm"] is None
        assert kpi["growth_rate_mm_per_day"] is None

    def test_data_completeness_score_type(self):
        kpi = compute_analysis(TIMELINE_TWO_EXAMS, "CASE_KPI")["kpi"]
        assert isinstance(kpi["data_completeness_score"], float)
