"""Tests for LLM enrichment module.

All Anthropic API calls are mocked — no network required.
A fake 'anthropic' module is injected into sys.modules before the module
under test is imported, so tests run even when the package is not installed.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Inject a fake 'anthropic' module before importing the module under test
# ---------------------------------------------------------------------------

_fake_anthropic = MagicMock(name="anthropic")
sys.modules.setdefault("anthropic", _fake_anthropic)
_fake_anthropic = sys.modules["anthropic"]  # always use whichever mock was installed first

from src.pipelines.llm_enrichment import _PROTECTED_KEYS, enrich_analysis  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_ANALYSIS: dict[str, Any] = {
    "case_id": "TEST_01",
    "patient_id": "PAT001",
    "overall_status": "unknown",
    "evidence": {
        "rule_applied": "no comparison",
        "progression_triggers": [],
        "response_triggers": [],
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
}

_FAKE_TOOL_INPUT = {
    "study_technique":      "Acquisition CT thoracique sans injection.",
    "preliminary_findings": "Plage HU [-1000, 400], compatible parenchyme pulmonaire.",
    "conclusions":          "Image de qualité satisfaisante. Interprétation clinique requise.",
}


def _setup_mock_api(tool_input: dict | None = _FAKE_TOOL_INPUT) -> MagicMock:
    """Configure _fake_anthropic to return a successful tool_use response."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "write_report_sections"
    tool_block.input = tool_input or {}

    response = MagicMock()
    response.content = [tool_block] if tool_input is not None else []

    _fake_anthropic.Anthropic.return_value.messages.create.return_value = response
    _fake_anthropic.Anthropic.reset_mock(return_value=True, side_effect=True)
    _fake_anthropic.Anthropic.return_value.messages.create.return_value = response
    return response


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_returns_unchanged(self):
        result = enrich_analysis(_BASE_ANALYSIS.copy(), dry_run=True)
        assert "llm_enriched" not in result

    def test_dry_run_never_calls_api(self):
        _fake_anthropic.reset_mock()
        enrich_analysis(_BASE_ANALYSIS.copy(), dry_run=True)
        _fake_anthropic.Anthropic.assert_not_called()


# ---------------------------------------------------------------------------
# No API key
# ---------------------------------------------------------------------------

class TestNoApiKey:
    def test_no_key_returns_unchanged(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = enrich_analysis(_BASE_ANALYSIS.copy(), api_key="")
        assert "llm_enriched" not in result

    def test_no_key_never_calls_api(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        _fake_anthropic.reset_mock()
        enrich_analysis(_BASE_ANALYSIS.copy(), api_key="")
        _fake_anthropic.Anthropic.assert_not_called()


# ---------------------------------------------------------------------------
# Successful enrichment
# ---------------------------------------------------------------------------

class TestEnrichmentSuccess:
    def setup_method(self):
        _setup_mock_api()

    def test_llm_enriched_flag_set(self):
        result = enrich_analysis(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result.get("llm_enriched") is True

    def test_narrative_fields_populated(self):
        result = enrich_analysis(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["latest_study_technique"] == _FAKE_TOOL_INPUT["study_technique"]
        assert result["latest_report"] == _FAKE_TOOL_INPUT["preliminary_findings"]
        assert result["latest_conclusions"] == _FAKE_TOOL_INPUT["conclusions"]

    def test_protected_fields_unchanged(self):
        original = _BASE_ANALYSIS.copy()
        result = enrich_analysis(original, api_key="fake-key")
        for key in _PROTECTED_KEYS:
            if key in original:
                assert result[key] == original[key], f"Protected field '{key}' was modified"

    def test_overall_status_never_changed(self):
        result = enrich_analysis(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["overall_status"] == "unknown"

    def test_dicom_block_never_changed(self):
        original = _BASE_ANALYSIS.copy()
        result = enrich_analysis(original, api_key="fake-key")
        assert result["dicom"] == original["dicom"]

    def test_kpi_never_changed(self):
        original = _BASE_ANALYSIS.copy()
        result = enrich_analysis(original, api_key="fake-key")
        assert result["kpi"] == original["kpi"]


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_api_exception_returns_original(self):
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = Exception("timeout")
        result = enrich_analysis(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert "llm_enriched" not in result
        # Reset side_effect for other tests
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = None

    def test_empty_content_returns_original(self):
        empty = MagicMock()
        empty.content = []
        _fake_anthropic.Anthropic.return_value.messages.create.return_value = empty
        result = enrich_analysis(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert "llm_enriched" not in result

    def test_original_fields_intact_after_failure(self):
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = RuntimeError("fail")
        result = enrich_analysis(_BASE_ANALYSIS.copy(), api_key="fake-key")
        assert result["overall_status"] == "unknown"
        assert result["case_id"] == "TEST_01"
        _fake_anthropic.Anthropic.return_value.messages.create.side_effect = None


# ---------------------------------------------------------------------------
# build_context integration
# ---------------------------------------------------------------------------

class TestBuildContextFallback:
    """LLM-enriched fields must flow into the report context (fallback priority)."""

    def test_llm_fields_appear_when_no_timeline(self):
        from src.pipelines.generate_report import build_context

        enriched = {
            **_BASE_ANALYSIS,
            "latest_study_technique": "Scanner CT thoracique.",
            "latest_report":          "Parenchyme normal.",
            "latest_conclusions":     "Bonne qualité.",
            "llm_enriched": True,
        }
        ctx = build_context([], enriched)
        assert ctx["latest_study_technique"] == "Scanner CT thoracique."
        assert ctx["latest_report"] == "Parenchyme normal."
        assert ctx["latest_conclusions"] == "Bonne qualité."

    def test_timeline_takes_priority_over_llm(self):
        from src.pipelines.generate_report import build_context

        timeline = [{
            "study_date": "2024-07-15",
            "report_sections": {
                "study_technique": "Technique Excel",
                "report":          "Rapport Excel",
                "conclusions":     "Conclusions Excel",
            },
        }]
        enriched = {
            **_BASE_ANALYSIS,
            "latest_study_technique": "LLM technique",
            "latest_report":          "LLM rapport",
            "latest_conclusions":     "LLM conclusions",
            "llm_enriched": True,
        }
        ctx = build_context(timeline, enriched)
        assert ctx["latest_study_technique"] == "Technique Excel"
        assert ctx["latest_report"] == "Rapport Excel"
        assert ctx["latest_conclusions"] == "Conclusions Excel"

    def test_no_enrichment_no_timeline_gives_none(self):
        from src.pipelines.generate_report import build_context

        ctx = build_context([], _BASE_ANALYSIS.copy())
        assert ctx["latest_study_technique"] is None
        assert ctx["latest_report"] is None
        assert ctx["latest_conclusions"] is None
