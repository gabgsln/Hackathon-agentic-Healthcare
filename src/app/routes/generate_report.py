"""FastAPI routes for report generation.

Imaging-first policy:
  - DICOM files are MANDATORY. Requests without images → HTTP 400.
  - Excel is optional. If provided, only patient/exam metadata is used
    (PatientID, StudyDate, AccessionNumber) — lesion sizes are ignored.
  - Lesion measurements come exclusively from DICOM + annotation JSON.
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from src.agents.orchestrator import Orchestrator
from src.core.config import settings
from src.core.types import ReportRequest
from src.pipelines.ingest_excel import ingest_excel
from src.reporting.renderer import Renderer

router = APIRouter()


@router.post("/generate", response_model=None)
async def generate_report(
    patient_id: str = Form(...),
    referring_physician: str = Form(default=""),
    output_format: str = Form(default="pdf"),
    dicom_files: list[UploadFile] = File(default=[]),
    excel_file: UploadFile | None = File(default=None),
    annotations_json: str = Form(default=""),
):
    """Generate a structured medical report from DICOM images.

    - **dicom_files**: DICOM .dcm files — **MANDATORY** (at least one required)
    - **excel_file**: Excel with patient metadata (optional; lesion sizes ignored)
    - **annotations_json**: Lesion annotations as JSON string (pixel coords + series UID)
    - **output_format**: "pdf" | "markdown" | "json"
    """
    # ── Images are mandatory — fail immediately if absent ────────────────────
    if not dicom_files or not any(f.filename for f in dicom_files):
        raise HTTPException(
            status_code=400,
            detail={
                "error":  "IMAGES_REQUIRED",
                "detail": "DICOM images are mandatory for report generation.",
            },
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # ── Save DICOM files ──────────────────────────────────────────────────
        dicom_dir = tmp / "dicom"
        dicom_dir.mkdir()
        dicom_paths: list[Path] = []
        for dcm in dicom_files:
            if dcm.filename:
                p = dicom_dir / dcm.filename
                p.write_bytes(await dcm.read())
                dicom_paths.append(p)
                logger.info(f"Received DICOM: {dcm.filename}")

        # ── Excel: save for metadata extraction only — NO lesion sizes ────────
        excel_path: Path | None = None
        if excel_file and excel_file.filename:
            excel_path = tmp / excel_file.filename
            excel_path.write_bytes(await excel_file.read())
            logger.info(f"Received Excel (metadata only, lesion sizes ignored): {excel_file.filename}")

        # ── Build request ─────────────────────────────────────────────────────
        request = ReportRequest(
            patient_id=patient_id,
            excel_path=excel_path,
            image_paths=dicom_paths,
            referring_physician=referring_physician or None,
            output_format=output_format,
        )

        try:
            # Excel → timeline for patient/exam metadata ONLY
            timeline = None
            if excel_path:
                timeline = ingest_excel(excel_path)

            # Run orchestrator (vision_tool is forced first inside orchestrator)
            orchestrator = Orchestrator()
            report = await orchestrator.run(
                request=request,
                timeline=timeline,
                dicom_paths=dicom_paths,
                annotations_json=annotations_json or None,
            )

            # ── Render output ─────────────────────────────────────────────────
            renderer = Renderer()
            output_path = tmp / f"report_{patient_id}"

            if output_format == "json":
                return JSONResponse(content=report.model_dump(mode="json"))

            elif output_format == "markdown":
                md_path = renderer.to_markdown(report, output_path.with_suffix(".md"))
                return FileResponse(
                    path=str(md_path),
                    media_type="text/markdown",
                    filename=f"report_{patient_id}.md",
                )
            else:  # pdf
                pdf_path = renderer.to_pdf(report, output_path.with_suffix(".pdf"))
                return FileResponse(
                    path=str(pdf_path),
                    media_type="application/pdf",
                    filename=f"report_{patient_id}.pdf",
                )

        except ValueError as exc:
            # Structured errors from vision_tool (MEASUREMENTS_REQUIRED, etc.)
            import json as _json
            try:
                detail = _json.loads(str(exc))
            except Exception:
                detail = str(exc)
            raise HTTPException(status_code=422, detail=detail) from exc

        except Exception as exc:
            logger.exception(f"Report generation failed for {patient_id}")
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/generate/from-manifest")
async def generate_from_manifest(patient_id: str):
    """Generate a report using a pre-configured patient from the manifest."""
    import json

    manifest_path = settings.data_dir / "manifests" / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")

    manifest = json.loads(manifest_path.read_text())
    case = next((c for c in manifest["cases"] if c["patient_id"] == patient_id), None)
    if not case:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not in manifest")

    dicom_paths = [Path(p) for p in case.get("dicom_files", [])]
    if not dicom_paths:
        raise HTTPException(
            status_code=400,
            detail={
                "error":  "IMAGES_REQUIRED",
                "detail": "No DICOM files configured for this case in the manifest.",
            },
        )

    excel_path = Path(case["excel_file"]) if case.get("excel_file") else None
    request = ReportRequest(
        patient_id=patient_id,
        excel_path=excel_path,
        image_paths=dicom_paths,
        output_format="json",
    )

    timeline = ingest_excel(excel_path) if excel_path and excel_path.exists() else None

    orchestrator = Orchestrator()
    report = await orchestrator.run(
        request=request,
        timeline=timeline,
        dicom_paths=dicom_paths,
        annotations_json=case.get("annotations_json"),
    )
    return report.model_dump(mode="json")
