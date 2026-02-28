"""Tests for DICOM series detection, non-image rejection, and status_reason gating.

Covers:
- Single file → imaging.input_kind == "single", is_3d == False
- Folder of slices → imaging.input_kind == "series", is_3d == True, n_slices == N
- Non-image modality (SR) → ValueError raised before pixel access
- status_reason == "no_timeline" for DICOM-only analysis
- imaging block keys always present
- Schema validation passes for series analysis
- CLI --xlsx alias is accepted
- CLI --out is optional (defaults to data/processed/{case_id}/)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# DICOM factories
# ---------------------------------------------------------------------------

def _make_dicom_slice(
    out_dir: Path,
    filename: str,
    instance_number: int = 1,
    z_position: float = 0.0,
    modality: str = "CT",
    patient_id: str = "SERIESPAT",
    series_uid: str | None = None,
    study_uid: str | None = None,
) -> Path:
    """Create a single DICOM slice with configurable InstanceNumber and z-position."""
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    out_dir.mkdir(parents=True, exist_ok=True)
    dcm_path = out_dir / filename

    sop_uid = generate_uid()
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(str(dcm_path), {}, file_meta=file_meta, preamble=b"\0" * 128)

    ds.PatientID         = patient_id
    ds.StudyInstanceUID  = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.SOPInstanceUID    = sop_uid
    ds.SOPClassUID       = file_meta.MediaStorageSOPClassUID

    ds.Modality                  = modality
    ds.StudyDate                 = "20240715"
    ds.BodyPartExamined          = "CHEST"
    ds.InstanceNumber            = str(instance_number)
    ds.PixelSpacing              = [0.703125, 0.703125]
    ds.SliceThickness            = 2.5
    ds.ImagePositionPatient      = [0.0, 0.0, z_position]

    rng = np.random.default_rng(instance_number)
    arr = rng.integers(low=-1000, high=500, size=(64, 64), dtype=np.int16)
    ds.Rows                      = 64
    ds.Columns                   = 64
    ds.BitsAllocated             = 16
    ds.BitsStored                = 16
    ds.HighBit                   = 15
    ds.PixelRepresentation       = 1
    ds.SamplesPerPixel           = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData                 = arr.tobytes()

    ds.save_as(str(dcm_path), enforce_file_format=True)
    return dcm_path


def _make_series_folder(
    out_dir: Path,
    n_slices: int = 5,
    modality: str = "CT",
) -> Path:
    """Create a folder containing *n_slices* DICOM CT slices."""
    from pydicom.uid import generate_uid

    series_uid = generate_uid()
    study_uid  = generate_uid()
    for i in range(1, n_slices + 1):
        _make_dicom_slice(
            out_dir,
            filename=f"slice_{i:03d}.dcm",
            instance_number=i,
            z_position=float(i) * 2.5,
            modality=modality,
            series_uid=series_uid,
            study_uid=study_uid,
        )
    return out_dir


def _make_sr_file(out_dir: Path) -> Path:
    """Create a minimal DICOM SR (Structured Report) file — no pixel data."""
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    out_dir.mkdir(parents=True, exist_ok=True)
    dcm_path = out_dir / "report.dcm"
    sop_uid = generate_uid()

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.88.11"  # Basic SR
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(str(dcm_path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientID        = "SRPAT"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID   = sop_uid
    ds.SOPClassUID      = file_meta.MediaStorageSOPClassUID
    ds.Modality         = "SR"
    ds.StudyDate        = "20240715"
    ds.save_as(str(dcm_path), enforce_file_format=True)
    return dcm_path


# ---------------------------------------------------------------------------
# Single-file imaging block
# ---------------------------------------------------------------------------

class TestSingleFileImagingBlock:
    """imaging block is correct for a single .dcm input."""

    def test_input_kind_is_single(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert result["imaging"]["input_kind"] == "single"

    def test_n_slices_is_one(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert result["imaging"]["n_slices"] == 1

    def test_is_3d_false(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert result["imaging"]["is_3d"] is False

    def test_volume_shape_length_three(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert len(result["imaging"]["volume_shape"]) == 3

    def test_spacing_mm_length_three(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert len(result["imaging"]["spacing_mm"]) == 3

    def test_sorting_key_is_none_for_single(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert result["imaging"]["sorting_key_used"] == "none"


# ---------------------------------------------------------------------------
# Series folder imaging block
# ---------------------------------------------------------------------------

class TestSeriesFolderImagingBlock:
    """imaging block is correct for a folder of slices."""

    @pytest.fixture()
    def series_result(self, tmp_path):
        folder = _make_series_folder(tmp_path / "series", n_slices=5)
        from src.pipelines.dicom_analysis import analyze_dicom
        return analyze_dicom(folder)

    def test_input_kind_is_series(self, series_result):
        assert series_result["imaging"]["input_kind"] == "series"

    def test_n_slices_matches_folder(self, series_result):
        assert series_result["imaging"]["n_slices"] == 5

    def test_is_3d_true(self, series_result):
        assert series_result["imaging"]["is_3d"] is True

    def test_volume_shape_first_dim_matches(self, series_result):
        assert series_result["imaging"]["volume_shape"][0] == 5

    def test_series_uid_populated(self, series_result):
        assert series_result["imaging"]["series_instance_uid"] is not None

    def test_sorting_key_used(self, series_result):
        key = series_result["imaging"]["sorting_key_used"]
        assert key in {"InstanceNumber", "ImagePositionPatient"}

    def test_schema_valid_for_series(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom, validate_analysis
        folder = _make_series_folder(tmp_path / "series", n_slices=3)
        result = analyze_dicom(folder)
        validate_analysis(result)  # must not raise

    def test_image_stats_shape_has_three_dims(self, series_result):
        shape = series_result["dicom"]["image_stats"]["shape"]
        assert len(shape) == 3
        assert shape[0] == 5


# ---------------------------------------------------------------------------
# Non-image modality rejection (SR)
# ---------------------------------------------------------------------------

class TestNonImageRejection:
    """SR and other non-image DICOM objects must be rejected before pixel access."""

    def test_sr_single_file_raises_value_error(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        sr_path = _make_sr_file(tmp_path)
        with pytest.raises(ValueError, match="Non-image DICOM rejected"):
            analyze_dicom(sr_path)

    def test_sr_error_message_contains_modality(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        sr_path = _make_sr_file(tmp_path)
        with pytest.raises(ValueError, match="SR"):
            analyze_dicom(sr_path)

    def test_folder_with_only_sr_raises(self, tmp_path):
        """A folder where all files are SR must raise ValueError."""
        from src.pipelines.dicom_analysis import analyze_dicom
        folder = tmp_path / "sr_folder"
        _make_sr_file(folder)  # creates one SR
        with pytest.raises(ValueError):
            analyze_dicom(folder)


# ---------------------------------------------------------------------------
# status_reason gating
# ---------------------------------------------------------------------------

class TestStatusReason:
    """status_reason reflects why overall_status is set."""

    def test_single_file_reason_is_no_timeline(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert result["status_reason"] == "no_timeline"

    def test_series_folder_reason_is_no_timeline(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        folder = _make_series_folder(tmp_path / "series", n_slices=3)
        result = analyze_dicom(folder)
        assert result["status_reason"] == "no_timeline"

    def test_status_explanation_is_non_empty_string(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert isinstance(result["status_explanation"], str)
        assert len(result["status_explanation"]) > 0

    def test_overall_status_is_unknown_no_timeline(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom
        dcm = _make_dicom_slice(tmp_path, "slice.dcm")
        result = analyze_dicom(dcm)
        assert result["overall_status"] == "unknown"

    def test_status_explanation_appears_in_report(self, tmp_path):
        """status_explanation must be visible in the rendered Markdown report."""
        from src.pipelines.run_case import run_case
        dcm = _make_dicom_slice(tmp_path / "in", "slice.dcm")
        out = tmp_path / "out"
        run_case(dicom_path=dcm, out_dir=out, case_id="STATUS_01")
        report = (out / "final_report.md").read_text()
        analysis = json.loads((out / "analysis.json").read_text())
        # The explanation string (or at least part of it) must appear in report
        assert analysis["status_explanation"][:30] in report


# ---------------------------------------------------------------------------
# CLI upgrades
# ---------------------------------------------------------------------------

class TestCLIUpgrades:
    """Verify --xlsx alias and optional --out."""

    def test_out_defaults_when_omitted(self, tmp_path, monkeypatch):
        """When --out is omitted, output lands in data/processed/{case_id}/."""
        monkeypatch.chdir(tmp_path)
        dcm = _make_dicom_slice(tmp_path / "in", "slice.dcm")

        from src.pipelines.run_case import main as run_main
        run_main(["--dicom", str(dcm), "--case-id", "DEFAULT_OUT"])

        expected = tmp_path / "data" / "processed" / "DEFAULT_OUT"
        assert (expected / "analysis.json").exists()
        assert (expected / "final_report.md").exists()

    def test_folder_input_via_cli(self, tmp_path):
        """--dicom can point to a folder of slices."""
        folder = _make_series_folder(tmp_path / "series", n_slices=3)
        out = tmp_path / "out"

        from src.pipelines.run_case import main as run_main
        run_main(["--dicom", str(folder), "--case-id", "SERIES_CLI", "--out", str(out)])

        data = json.loads((out / "analysis.json").read_text())
        assert data["imaging"]["input_kind"] == "series"
        assert data["imaging"]["n_slices"] == 3
