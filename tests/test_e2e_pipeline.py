"""End-to-end pipeline tests.

test_e2e_success      — DICOM present, full pipeline runs, outputs exist, schema valid.
test_e2e_missing_dicom — No DICOM, pipeline exits with non-zero status.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Synthetic DICOM factory
# ---------------------------------------------------------------------------

def _make_synthetic_dicom(out_dir: Path, patient_id: str = "TESTPAT001") -> Path:
    """Create a minimal but fully valid DICOM CT slice for testing.

    Uses pydicom to write a real .dcm file with:
    - All required metadata tags
    - PixelSpacing and SliceThickness
    - A 64×64 int16 pixel array (CT HU range)
    """
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    out_dir.mkdir(parents=True, exist_ok=True)
    dcm_path = out_dir / "slice_001.dcm"

    sop_uid = generate_uid()

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.2"  # CT Storage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(str(dcm_path), {}, file_meta=file_meta, preamble=b"\0" * 128)

    # Patient / study / series
    ds.PatientID         = patient_id
    ds.StudyInstanceUID  = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID    = sop_uid
    ds.SOPClassUID       = file_meta.MediaStorageSOPClassUID

    # Descriptors
    ds.Modality                  = "CT"
    ds.StudyDate                 = "20240715"
    ds.BodyPartExamined          = "CHEST"
    ds.SeriesDescription         = "CT THORAX SYNTHETIQUE"
    ds.InstanceNumber            = "1"
    ds.PixelSpacing              = [0.703125, 0.703125]
    ds.SliceThickness            = 1.5

    # Pixel data — 64×64 CT HU range signed int16
    rng = np.random.default_rng(42)
    arr = rng.integers(low=-1000, high=500, size=(64, 64), dtype=np.int16)
    ds.Rows                      = 64
    ds.Columns                   = 64
    ds.BitsAllocated             = 16
    ds.BitsStored                = 16
    ds.HighBit                   = 15
    ds.PixelRepresentation       = 1   # signed
    ds.SamplesPerPixel           = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData                 = arr.tobytes()

    ds.save_as(str(dcm_path), enforce_file_format=True)
    return dcm_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_analysis(out_dir: Path) -> dict:
    return json.loads((out_dir / "analysis.json").read_text())


# ---------------------------------------------------------------------------
# test_e2e_success
# ---------------------------------------------------------------------------

class TestE2ESuccess:
    """Full pipeline: DICOM → analysis.json (schema-valid) → final_report.md."""

    def test_outputs_exist(self, tmp_path):
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        outputs = run_case(dicom_path=dcm_path, out_dir=out_dir, case_id="TEST_01")

        assert outputs["analysis"].exists(), "analysis.json must be created"
        assert outputs["report"].exists(),   "final_report.md must be created"

    def test_analysis_json_schema_valid(self, tmp_path):
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.dicom_analysis import validate_analysis
        from src.pipelines.run_case import run_case

        run_case(dicom_path=dcm_path, out_dir=out_dir, case_id="TEST_01")

        analysis = _load_analysis(out_dir)
        validate_analysis(analysis)  # raises jsonschema.ValidationError on failure

    def test_analysis_has_dicom_block(self, tmp_path):
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        run_case(dicom_path=dcm_path, out_dir=out_dir, case_id="TEST_01")

        analysis = _load_analysis(out_dir)
        assert "dicom" in analysis,               "analysis.json must contain 'dicom' key"
        assert "metadata" in analysis["dicom"],   "dicom block must contain 'metadata'"
        assert "image_stats" in analysis["dicom"], "dicom block must contain 'image_stats'"

    def test_metadata_fields_populated(self, tmp_path):
        dcm_path = _make_synthetic_dicom(tmp_path / "input", patient_id="P999")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        run_case(dicom_path=dcm_path, out_dir=out_dir)

        meta = _load_analysis(out_dir)["dicom"]["metadata"]
        assert meta["PatientID"]        == "P999"
        assert meta["Modality"]         == "CT"
        assert meta["StudyDate"]        == "2024-07-15"
        assert meta["BodyPartExamined"] == "CHEST"
        assert meta["PixelSpacing"]     == [0.703125, 0.703125]
        assert meta["SliceThickness"]   == pytest.approx(1.5)

    def test_pixel_array_actually_loaded(self, tmp_path):
        """pixel_array stats must reflect real pixel values, not defaults."""
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        run_case(dicom_path=dcm_path, out_dir=out_dir)

        stats = _load_analysis(out_dir)["dicom"]["image_stats"]
        assert stats["shape"] == [64, 64]
        # Synthetic array range: [-1000, 500) → max must be > 0
        assert stats["max"] > 0
        assert stats["min"] < 0         # CT HU range has negatives
        assert stats["std"] > 0         # non-constant image
        assert 0.0 <= stats["data_consistency_score"] <= 1.0

    def test_report_contains_imaging_section(self, tmp_path):
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        run_case(dicom_path=dcm_path, out_dir=out_dir)

        report = (out_dir / "final_report.md").read_text()
        assert "Imaging Findings" in report
        assert "CT" in report                   # Modality
        assert "CHEST" in report                # BodyPartExamined
        assert "0.703125" in report             # PixelSpacing

    def test_overall_status_is_unknown_for_single_instance(self, tmp_path):
        """A single DICOM cannot produce a comparison → status must be 'unknown'."""
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        run_case(dicom_path=dcm_path, out_dir=out_dir)

        assert _load_analysis(out_dir)["overall_status"] == "unknown"

    def test_no_timeline_without_excel(self, tmp_path):
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        outputs = run_case(dicom_path=dcm_path, out_dir=out_dir)

        assert "timeline" not in outputs
        assert not (out_dir / "timeline.json").exists()

    def test_case_id_propagated(self, tmp_path):
        dcm_path = _make_synthetic_dicom(tmp_path / "input")
        out_dir  = tmp_path / "output"

        from src.pipelines.run_case import run_case
        run_case(dicom_path=dcm_path, out_dir=out_dir, case_id="MY_CASE_42")

        analysis = _load_analysis(out_dir)
        assert analysis["case_id"] == "MY_CASE_42"


# ---------------------------------------------------------------------------
# test_e2e_missing_dicom
# ---------------------------------------------------------------------------

class TestE2EMissingDicom:
    """Pipeline must refuse to run and exit(1) when DICOM is absent."""

    def test_missing_dicom_exits_nonzero(self, tmp_path):
        from src.pipelines.run_case import run_case

        with pytest.raises(SystemExit) as exc_info:
            run_case(
                dicom_path=Path("/nonexistent/totally_fake.dcm"),
                out_dir=tmp_path / "output",
            )
        assert exc_info.value.code != 0, "Pipeline must exit with non-zero status"

    def test_no_output_files_on_missing_dicom(self, tmp_path):
        from src.pipelines.run_case import run_case

        out_dir = tmp_path / "output"
        with pytest.raises(SystemExit):
            run_case(
                dicom_path=Path("/nonexistent/totally_fake.dcm"),
                out_dir=out_dir,
            )
        assert not (out_dir / "analysis.json").exists()
        assert not (out_dir / "final_report.md").exists()

    def test_cli_missing_dicom_exits_nonzero(self, tmp_path):
        """The --dicom CLI flag with a missing path must exit(1)."""
        from src.pipelines.run_case import main as run_main

        with pytest.raises(SystemExit) as exc_info:
            run_main([
                "--dicom", str(tmp_path / "does_not_exist.dcm"),
                "--out",   str(tmp_path / "output"),
            ])
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Standalone dicom_analysis tests
# ---------------------------------------------------------------------------

class TestDicomAnalysis:
    """Unit tests for the dicom_analysis module."""

    def test_analyze_dicom_returns_valid_dict(self, tmp_path):
        dcm = _make_synthetic_dicom(tmp_path)
        from src.pipelines.dicom_analysis import analyze_dicom, validate_analysis

        result = analyze_dicom(dcm, case_id="UNIT_01")
        validate_analysis(result)   # must not raise

    def test_missing_file_raises_file_not_found(self, tmp_path):
        from src.pipelines.dicom_analysis import analyze_dicom

        with pytest.raises(FileNotFoundError, match="DICOM input is required"):
            analyze_dicom(Path("/nope/fake.dcm"))

    def test_pixel_array_is_used(self, tmp_path):
        dcm = _make_synthetic_dicom(tmp_path)
        from src.pipelines.dicom_analysis import analyze_dicom

        result = analyze_dicom(dcm)
        stats = result["dicom"]["image_stats"]
        # If pixel_array were not loaded, std would be 0 or missing
        assert stats["std"] > 0
        assert stats["shape"] == [64, 64]

    def test_schema_validation_fails_on_missing_field(self, tmp_path):
        """Remove a required field → validate_analysis must raise."""
        dcm = _make_synthetic_dicom(tmp_path)
        import jsonschema

        from src.pipelines.dicom_analysis import analyze_dicom, validate_analysis

        result = analyze_dicom(dcm)
        del result["dicom"]  # remove mandatory block

        with pytest.raises(jsonschema.ValidationError):
            validate_analysis(result)

    def test_data_consistency_score_in_range(self, tmp_path):
        dcm = _make_synthetic_dicom(tmp_path)
        from src.pipelines.dicom_analysis import analyze_dicom

        result = analyze_dicom(dcm)
        score = result["dicom"]["image_stats"]["data_consistency_score"]
        assert 0.0 <= score <= 1.0

    def test_cli_produces_output(self, tmp_path):
        dcm = _make_synthetic_dicom(tmp_path / "raw")
        out_path = tmp_path / "out" / "analysis.json"

        from src.pipelines.dicom_analysis import main as dicom_main
        dicom_main([
            "--dicom",    str(dcm),
            "--case-id",  "CLI_TEST",
            "--out",      str(out_path),
        ])

        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["case_id"] == "CLI_TEST"
        assert "dicom" in data
