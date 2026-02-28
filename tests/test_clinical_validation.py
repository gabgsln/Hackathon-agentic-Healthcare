"""Tests for the Clinical Validation Agent.

All Anthropic API calls are mocked — no network required.
A fake 'anthropic' module is injected before the module under test is imported,
so tests run even when the anthropic package is not installed.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Inject a fake 'anthropic' module BEFORE importing the module under test
# ---------------------------------------------------------------------------

_fake_anthropic = MagicMock(name="anthropic")
sys.modules.setdefault("anthropic", _fake_anthropic)
_fake_anthropic = sys.modules["anthropic"]  # always use whichever mock was installed first

from src.pipelines.clinical_validation import _PROTECTED_KEYS, validate_clinical  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_ANALYSIS: dict[str, Any] = {
    "pipeline_version": "0.2.0",
    "case_id": "TEST_01",
    "patient_id": "PAT001",
    "overall_status": "unknown",
    "status_reason": "no_timeline",
    "status_explanation": "Analyse DICOM unique.",
    "evidence": {
        "rule_applied": "no comparison",
        "progression_triggers": [],
        "response_triggers":    [],
        "thresholds": {"progression_pct": 20.0, "progression_abs_mm": 5.0, "response_pct": 30.0},
    },
    "lesion_deltas": [],
    "kpi": {
        "data_completeness_score": 100.0,
        "lesion_count_baseline": 0,
        "lesion_count_current": 0,
        "lesion_count_delta": 0,
    },
    "dicom": {
        "metadata": {
            "PatientID": "PAT001",
            "Modality": "CT",
            "BodyPartExamined": "CHEST",
            "StudyDate": "2024-07-15",
            "SliceThickness": 1.5,
            "PixelSpacing": [0.703125, 0.703125],
            "StudyInstanceUID": "1.2.3",
            "SeriesInstanceUID": "1.2.4",
        },
        "image_stats": {
            "shape": [128, 128],
            "dtype": "float32",
            "min": -1000.0, "max": 400.0, "mean": -200.0, "std": 300.0,
            "data_consistency_score": 1.0,
        },
    },
    "imaging": {
        "input_kind": "single",
        "n_slices": 1,
        "volume_shape": [1, 128, 128],
        "spacing_mm": [1.5, 0.703125, 0.703125],
        "series_instance_uid": "1.2.4",
        "sorting_key_used": "none",
        "is_3d": False,
    },
}

_FAKE_TOOL_OUTPUT: dict[str, Any] = {
    "confidence_score": 0.92,
    "clinical_consistency_score": 0.88,
    "anomaly_flags": ["single_slice_only"],
    "validation_notes": "Analyse de coupe unique — données volumiques indisponibles.",
}


def _setup_mock_api(tool_output: dict | None = _FAKE_TOOL_OUTPUT) -> MagicMock:
    """Configure _fake_anthropic to return a successful tool_use response."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "validate_clinical_data"
    tool_block.input = tool_output or {}

    response = MagicMock()
    response.content = [tool_block] if tool_output is not None else []

    _fake_anthropic.Anthropic.reset_mock(return_value=True, side_effect=True)
    _fake_anthropic.Anthropic.return_value.messages.create.return_value = response
    return response


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_returns_unchanged(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), dry_run=True)
        assert "validation" not in result

    def test_dry_run_never_calls_api(self):
        _fake_anthropic.reset_mock()
        validate_clinical(_BASE_ANALYSIS.copy(), dry_run=True)
        _fake_anthropic.Anthropic.assert_not_called()


# ---------------------------------------------------------------------------
# No API key
# ---------------------------------------------------------------------------

class TestNoApiKey:
    def test_no_key_returns_unchanged(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="")
        assert "validation" not in result

    def test_no_key_never_calls_api(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        _fake_anthropic.reset_mock()
        validate_clinical(_BASE_ANALYSIS.copy(), api_key="")
        _fake_anthropic.Anthropic.assert_not_called()


# ---------------------------------------------------------------------------
# Successful validation
# ---------------------------------------------------------------------------

class TestValidationSuccess:
    def setup_method(self):
        _setup_mock_api()

    def test_validation_block_present(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert "validation" in result

    def test_confidence_score_in_range(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        score = result["validation"]["confidence_score"]
        assert 0.0 <= score <= 1.0

    def test_clinical_consistency_in_range(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        score = result["validation"]["clinical_consistency_score"]
        assert 0.0 <= score <= 1.0

    def test_scores_match_tool_output(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["validation"]["confidence_score"] == pytest.approx(0.92)
        assert result["validation"]["clinical_consistency_score"] == pytest.approx(0.88)

    def test_anomaly_flags_is_list(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert isinstance(result["validation"]["anomaly_flags"], list)

    def test_anomaly_flags_match_tool_output(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["validation"]["anomaly_flags"] == ["single_slice_only"]

    def test_validated_at_is_string(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert isinstance(result["validation"]["validated_at"], str)
        assert "T" in result["validation"]["validated_at"]  # ISO-8601

    def test_model_used_present(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["validation"]["model_used"] == "claude-haiku-4-5-20251001"

    def test_validation_notes_present(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["validation"]["validation_notes"] is not None


# ---------------------------------------------------------------------------
# Protected fields never modified
# ---------------------------------------------------------------------------

class TestProtectedFields:
    def setup_method(self):
        _setup_mock_api()

    def test_overall_status_unchanged(self):
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["overall_status"] == "unknown"

    def test_kpi_unchanged(self):
        original = _BASE_ANALYSIS.copy()
        result = validate_clinical(original, api_key="fake-key")
        assert result["kpi"] == original["kpi"]

    def test_dicom_block_unchanged(self):
        original = _BASE_ANALYSIS.copy()
        result = validate_clinical(original, api_key="fake-key")
        assert result["dicom"] == original["dicom"]

    def test_all_protected_keys_unchanged(self):
        original = _BASE_ANALYSIS.copy()
        result = validate_clinical(original, api_key="fake-key")
        for key in _PROTECTED_KEYS:
            if key in original:
                assert result[key] == original[key], f"Protected key '{key}' was modified"

    def test_pipeline_version_unchanged(self):
        original = _BASE_ANALYSIS.copy()
        result = validate_clinical(original, api_key="fake-key")
        assert result["pipeline_version"] == "0.2.0"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_api_exception_returns_original(self):
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = Exception("timeout")
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert "validation" not in result
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = None

    def test_empty_content_returns_original(self):
        _setup_mock_api(tool_output=None)
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert "validation" not in result

    def test_runtime_error_returns_original(self):
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = RuntimeError("fail")
        result = validate_clinical(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["case_id"] == "TEST_01"
        assert result["overall_status"] == "unknown"
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = None


# ---------------------------------------------------------------------------
# Integration: validation appears in report
# ---------------------------------------------------------------------------

class TestValidationInReport:
    def test_validation_block_in_report_context(self):
        """validation block from analysis must flow into generate_report context."""
        from src.pipelines.generate_report import build_context

        analysis_with_validation = {
            **_BASE_ANALYSIS,
            "validation": {
                "confidence_score": 0.9,
                "clinical_consistency_score": 0.85,
                "anomaly_flags": ["test_flag"],
                "validation_notes": "Test note.",
                "validated_at": "2024-07-15T12:00:00+00:00",
                "model_used": "claude-haiku-4-5-20251001",
            },
        }
        ctx = build_context([], analysis_with_validation)
        assert ctx["validation"] is not None
        assert ctx["validation"]["confidence_score"] == pytest.approx(0.9)
        assert ctx["validation"]["anomaly_flags"] == ["test_flag"]

    def test_no_validation_context_is_none(self):
        """When validation is absent, context key is None — template handles it gracefully."""
        from src.pipelines.generate_report import build_context

        ctx = build_context([], _BASE_ANALYSIS.copy())
        assert ctx["validation"] is None


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

import pytest  # noqa: E402 (placed at end to avoid shadowing)
