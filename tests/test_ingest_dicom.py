"""Tests for dicom_utils and ingest_dicom — uses mocked pydicom Datasets (no real files)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipelines.dicom_utils import (
    build_study_summary,
    group_by_accession,
    parse_dicom_date,
    read_dicom_metadata,
)


# ---------------------------------------------------------------------------
# Helpers — build fake pydicom.Dataset-like objects
# ---------------------------------------------------------------------------

def _fake_ds(
    accession: str = "ACC001",
    study_uid: str = "1.2.3",
    series_uid: str = "1.2.3.1",
    modality: str = "CT",
    study_date: str = "20240615",
    series_desc: str = "Chest CT",
    series_number: int = 3,
) -> MagicMock:
    """Return a MagicMock that behaves like a minimal pydicom Dataset."""
    ds = MagicMock()
    ds.AccessionNumber = accession
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = modality
    ds.StudyDate = study_date
    ds.SeriesDescription = series_desc
    ds.SeriesNumber = series_number
    return ds


# ---------------------------------------------------------------------------
# parse_dicom_date
# ---------------------------------------------------------------------------

class TestParseDicomDate:
    def test_valid_yyyymmdd(self):
        assert parse_dicom_date("20240615") == "2024-06-15"

    def test_valid_start_of_year(self):
        assert parse_dicom_date("20240101") == "2024-01-01"

    def test_empty_string(self):
        assert parse_dicom_date("") is None

    def test_wrong_length(self):
        assert parse_dicom_date("202406") is None

    def test_non_digit(self):
        assert parse_dicom_date("2024-06-15") is None  # has dashes → not 8 digits

    def test_none_input(self):
        assert parse_dicom_date(None) is None


# ---------------------------------------------------------------------------
# read_dicom_metadata
# ---------------------------------------------------------------------------

class TestReadDicomMetadata:
    def test_basic_fields_extracted(self):
        ds = _fake_ds()
        meta = read_dicom_metadata(ds)
        assert meta["accession_number"] == "ACC001"
        assert meta["study_instance_uid"] == "1.2.3"
        assert meta["series_instance_uid"] == "1.2.3.1"
        assert meta["modality"] == "CT"
        assert meta["study_date"] == "2024-06-15"
        assert meta["series_description"] == "Chest CT"
        assert meta["series_number"] == 3

    def test_seg_modality(self):
        ds = _fake_ds(modality="SEG", series_uid="1.2.3.99")
        meta = read_dicom_metadata(ds)
        assert meta["modality"] == "SEG"

    def test_missing_optional_field(self):
        ds = MagicMock()
        ds.AccessionNumber = "ACC002"
        ds.StudyInstanceUID = "9.9.9"
        ds.SeriesInstanceUID = "9.9.9.1"
        ds.Modality = "CT"
        ds.StudyDate = "20240101"
        ds.SeriesDescription = ""
        ds.SeriesNumber = None
        meta = read_dicom_metadata(ds)
        assert meta["series_number"] is None

    def test_all_keys_present(self):
        ds = _fake_ds()
        meta = read_dicom_metadata(ds)
        expected_keys = {
            "accession_number", "study_instance_uid", "series_instance_uid",
            "study_date", "modality", "series_description", "series_number",
        }
        assert set(meta.keys()) == expected_keys


# ---------------------------------------------------------------------------
# group_by_accession
# ---------------------------------------------------------------------------

class TestGroupByAccession:
    def _records(self, accessions: list[str]) -> list[dict]:
        return [{"accession_number": a, "series_instance_uid": f"s{i}"}
                for i, a in enumerate(accessions)]

    def test_single_group(self):
        groups = group_by_accession(self._records(["A", "A", "A"]))
        assert list(groups.keys()) == ["A"]
        assert len(groups["A"]) == 3

    def test_multiple_groups(self):
        groups = group_by_accession(self._records(["A", "B", "A"]))
        assert set(groups.keys()) == {"A", "B"}
        assert len(groups["A"]) == 2
        assert len(groups["B"]) == 1

    def test_empty_accession_bucketed(self):
        records = [{"accession_number": "", "series_instance_uid": "s0"}]
        groups = group_by_accession(records)
        assert "" in groups

    def test_empty_input(self):
        assert group_by_accession([]) == {}


# ---------------------------------------------------------------------------
# build_study_summary
# ---------------------------------------------------------------------------

def _make_records(
    accession: str,
    series: list[dict],
) -> list[dict]:
    """Helper to build a list of per-file records for one study."""
    records = []
    for s in series:
        for _ in range(s.get("file_count", 1)):
            records.append({
                "accession_number": accession,
                "study_instance_uid": "1.2.3",
                "series_instance_uid": s["series_uid"],
                "study_date": "2024-06-15",
                "modality": s["modality"],
                "series_description": s.get("desc", ""),
                "series_number": s.get("num"),
            })
    return records


class TestBuildStudySummary:
    def test_basic_structure(self):
        records = _make_records("ACC001", [
            {"series_uid": "s1", "modality": "CT", "file_count": 150, "num": 3},
        ])
        summary = build_study_summary(records)
        assert summary["study_instance_uid"] == "1.2.3"
        assert summary["study_date"] == "2024-06-15"
        assert summary["ct_series_uid"] == "s1"
        assert summary["seg_series_uid"] is None
        assert len(summary["series"]) == 1
        assert summary["series"][0]["file_count"] == 150

    def test_ct_and_seg_detected(self):
        records = _make_records("ACC001", [
            {"series_uid": "s_ct", "modality": "CT",  "file_count": 100, "num": 1},
            {"series_uid": "s_seg", "modality": "SEG", "file_count": 1,   "num": 2},
        ])
        summary = build_study_summary(records)
        assert summary["ct_series_uid"] == "s_ct"
        assert summary["seg_series_uid"] == "s_seg"

    def test_multiple_series_sorted_by_number(self):
        records = _make_records("ACC001", [
            {"series_uid": "s3", "modality": "CT", "num": 3},
            {"series_uid": "s1", "modality": "CT", "num": 1},
        ])
        summary = build_study_summary(records)
        assert summary["series"][0]["series_number"] == 1

    def test_file_count_per_series(self):
        records = _make_records("ACC001", [
            {"series_uid": "s1", "modality": "CT", "file_count": 80, "num": 1},
            {"series_uid": "s2", "modality": "CT", "file_count": 40, "num": 2},
        ])
        summary = build_study_summary(records)
        counts = {s["series_instance_uid"]: s["file_count"] for s in summary["series"]}
        assert counts["s1"] == 80
        assert counts["s2"] == 40

    def test_no_ct_returns_none(self):
        records = _make_records("ACC001", [
            {"series_uid": "s1", "modality": "MR", "num": 1},
        ])
        summary = build_study_summary(records)
        assert summary["ct_series_uid"] is None

    def test_empty_records_returns_empty_dict(self):
        assert build_study_summary([]) == {}


# ---------------------------------------------------------------------------
# enrich_timeline integration (mocking scan_dicom_dir)
# ---------------------------------------------------------------------------

class TestEnrichTimeline:
    TIMELINE = [
        {"patient_id": "P001", "accession_number": "ACC001",
         "study_date": "2024-06-15", "lesion_sizes_mm": [10.0],
         "report_raw": "", "report_sections": {}},
        {"patient_id": "P001", "accession_number": "ACC002",
         "study_date": "2025-01-01", "lesion_sizes_mm": [12.0],
         "report_raw": "", "report_sections": {}},
    ]

    DICOM_RECORDS = [
        {"accession_number": "ACC001", "study_instance_uid": "1.2.3",
         "series_instance_uid": "1.2.3.1", "study_date": "2024-06-15",
         "modality": "CT", "series_description": "Chest", "series_number": 1,
         "file_path": "/fake/ACC001/slice001.dcm"},
        {"accession_number": "ACC001", "study_instance_uid": "1.2.3",
         "series_instance_uid": "1.2.3.1", "study_date": "2024-06-15",
         "modality": "CT", "series_description": "Chest", "series_number": 1,
         "file_path": "/fake/ACC001/slice002.dcm"},
    ]

    def test_matched_exam_gets_dicom_field(self):
        from src.pipelines.ingest_dicom import enrich_timeline

        with patch("src.pipelines.ingest_dicom.scan_dicom_dir", return_value=self.DICOM_RECORDS):
            enriched = enrich_timeline(self.TIMELINE, Path("/fake"))

        acc001_exam = next(e for e in enriched if e["accession_number"] == "ACC001")
        assert acc001_exam["dicom"] is not None
        assert acc001_exam["dicom"]["ct_series_uid"] == "1.2.3.1"

    def test_unmatched_exam_gets_null_dicom(self):
        from src.pipelines.ingest_dicom import enrich_timeline

        with patch("src.pipelines.ingest_dicom.scan_dicom_dir", return_value=self.DICOM_RECORDS):
            enriched = enrich_timeline(self.TIMELINE, Path("/fake"))

        acc002_exam = next(e for e in enriched if e["accession_number"] == "ACC002")
        assert acc002_exam["dicom"] is None

    def test_original_fields_preserved(self):
        from src.pipelines.ingest_dicom import enrich_timeline

        with patch("src.pipelines.ingest_dicom.scan_dicom_dir", return_value=[]):
            enriched = enrich_timeline(self.TIMELINE, Path("/fake"))

        assert enriched[0]["patient_id"] == "P001"
        assert enriched[0]["lesion_sizes_mm"] == [10.0]
        assert enriched[0]["dicom"] is None
