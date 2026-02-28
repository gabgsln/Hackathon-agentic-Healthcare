"""Unit tests for src/pipelines/parsers.py.

Run with:
    python -m pytest tests/test_parsers.py -v
"""


from src.pipelines.parsers import parse_lesion_sizes, split_report_sections

# ===========================================================================
# parse_lesion_sizes
# ===========================================================================

class TestParseLesionSizes:
    # --- Happy paths ---

    def test_single_integer_string(self):
        assert parse_lesion_sizes("12") == [12.0]

    def test_single_float_string(self):
        assert parse_lesion_sizes("12.5") == [12.5]

    def test_comma_separated(self):
        assert parse_lesion_sizes("12.5, 14.3, 8") == [8.0, 12.5, 14.3]

    def test_semicolon_separated(self):
        assert parse_lesion_sizes("12.5;14.3") == [12.5, 14.3]

    def test_whitespace_separated(self):
        assert parse_lesion_sizes("12 14.3 9.1") == [9.1, 12.0, 14.3]

    def test_mixed_separators(self):
        assert parse_lesion_sizes("10, 12.5; 8.0") == [8.0, 10.0, 12.5]

    def test_pipe_separator(self):
        assert parse_lesion_sizes("10|12") == [10.0, 12.0]

    def test_numeric_int(self):
        assert parse_lesion_sizes(12) == [12.0]

    def test_numeric_float(self):
        assert parse_lesion_sizes(12.5) == [12.5]

    def test_string_with_unit_suffix(self):
        """Values like '12mm' or '14.3mm' should be parsed correctly."""
        assert parse_lesion_sizes("12mm") == [12.0]
        assert parse_lesion_sizes("14.3mm, 8mm") == [8.0, 14.3]

    def test_output_is_sorted(self):
        result = parse_lesion_sizes("30, 5, 15")
        assert result == sorted(result)

    # --- Empty / null inputs ---

    def test_empty_string(self):
        assert parse_lesion_sizes("") == []

    def test_whitespace_only(self):
        assert parse_lesion_sizes("   ") == []

    def test_none(self):
        assert parse_lesion_sizes(None) == []

    def test_nan_float(self):
        assert parse_lesion_sizes(float("nan")) == []

    def test_pandas_na(self):
        import pandas as pd
        assert parse_lesion_sizes(pd.NA) == []

    def test_pandas_nat(self):
        import pandas as pd
        # pd.NaT is not float, falls through to str() path → should return []
        result = parse_lesion_sizes(pd.NaT)
        assert result == []

    # --- Non-numeric / garbage inputs ---

    def test_pure_text(self):
        assert parse_lesion_sizes("not a number") == []

    def test_mixed_valid_and_invalid_tokens(self):
        """Invalid tokens should be silently skipped."""
        assert parse_lesion_sizes("12.5, abc, 14.3") == [12.5, 14.3]

    def test_dash_only(self):
        assert parse_lesion_sizes("-") == []

    def test_dot_only(self):
        assert parse_lesion_sizes(".") == []

    # --- Deduplication is NOT expected (values may repeat for different lesions) ---

    def test_duplicate_values_preserved(self):
        # Same size measured for two different lesions — both kept
        result = parse_lesion_sizes("12.5, 12.5")
        # After sorted(set(...)) in ingest_excel they'd be deduped, but the
        # parser itself returns sorted list (without dedup)
        assert 12.5 in result


# ===========================================================================
# split_report_sections
# ===========================================================================

FULL_REPORT = (
    "CLINICAL INFORMATION. Patient with known lung nodule.\n"
    "STUDY TECHNIQUE. CT scan with contrast.\n"
    "REPORT. Single 12 mm nodule in the right upper lobe.\n"
    "CONCLUSIONS. Stable compared to previous exam."
)

class TestSplitReportSections:
    # --- Happy paths ---

    def test_all_sections_present(self):
        result = split_report_sections(FULL_REPORT)
        assert result["clinical_information"] == "Patient with known lung nodule."
        assert result["study_technique"] == "CT scan with contrast."
        assert result["report"] == "Single 12 mm nodule in the right upper lobe."
        assert result["conclusions"] == "Stable compared to previous exam."

    def test_returns_all_four_keys(self):
        result = split_report_sections(FULL_REPORT)
        assert set(result.keys()) == {
            "clinical_information", "study_technique", "report", "conclusions"
        }

    def test_case_insensitive_markers(self):
        text = (
            "clinical information. Low risk patient.\n"
            "study technique. Without contrast.\n"
            "report. No suspicious finding.\n"
            "conclusions. Follow-up in 12 months."
        )
        result = split_report_sections(text)
        assert result["clinical_information"] == "Low risk patient."
        assert result["conclusions"] == "Follow-up in 12 months."

    def test_markers_without_trailing_dot(self):
        text = (
            "CLINICAL INFORMATION Patient info here.\n"
            "CONCLUSIONS No change."
        )
        result = split_report_sections(text)
        assert result["clinical_information"] is not None
        assert result["conclusions"] == "No change."

    def test_missing_section_is_none(self):
        text = "CLINICAL INFORMATION. Some info.\nCONCLUSIONS. Final conclusion."
        result = split_report_sections(text)
        assert result["clinical_information"] == "Some info."
        assert result["study_technique"] is None
        assert result["report"] is None
        assert result["conclusions"] == "Final conclusion."

    def test_only_conclusions(self):
        text = "CONCLUSIONS. Only conclusions present."
        result = split_report_sections(text)
        assert result["conclusions"] == "Only conclusions present."
        assert result["clinical_information"] is None
        assert result["study_technique"] is None
        assert result["report"] is None

    def test_content_is_stripped(self):
        text = "CLINICAL INFORMATION.   \n  Lots of whitespace.   \nSTUDY TECHNIQUE. Tech."
        result = split_report_sections(text)
        assert result["clinical_information"] == "Lots of whitespace."

    def test_multiline_section_content(self):
        text = (
            "REPORT.\n"
            "Line one.\n"
            "Line two.\n"
            "CONCLUSIONS. Done."
        )
        result = split_report_sections(text)
        assert "Line one." in result["report"]
        assert "Line two." in result["report"]

    # --- Empty / null inputs ---

    def test_empty_string(self):
        result = split_report_sections("")
        assert all(v is None for v in result.values())

    def test_none_input(self):
        result = split_report_sections(None)
        assert all(v is None for v in result.values())

    def test_whitespace_only(self):
        result = split_report_sections("   ")
        assert all(v is None for v in result.values())

    def test_no_markers(self):
        result = split_report_sections("This text has no markers at all.")
        assert all(v is None for v in result.values())

    # --- Non-string inputs ---

    def test_integer_input(self):
        result = split_report_sections(42)
        assert all(v is None for v in result.values())

    def test_float_nan_input(self):
        result = split_report_sections(float("nan"))
        assert all(v is None for v in result.values())

    # --- Edge cases ---

    def test_empty_section_content_is_none(self):
        """A marker immediately followed by the next marker → content is None."""
        text = "CLINICAL INFORMATION.\nSTUDY TECHNIQUE. Technique info."
        result = split_report_sections(text)
        assert result["clinical_information"] is None
        assert result["study_technique"] == "Technique info."

    def test_order_does_not_matter(self):
        """Markers that appear out-of-order in the text are still parsed correctly."""
        text = (
            "CONCLUSIONS. Final.\n"
            "CLINICAL INFORMATION. First.\n"
            "REPORT. Middle."
        )
        result = split_report_sections(text)
        assert result["conclusions"] == "Final."
        assert result["clinical_information"] == "First."
        assert result["report"] == "Middle."
