import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from src.agents.orchestrator import Orchestrator
from src.core.config import settings
from src.core.types import GeneratedReport, ReportRequest
from src.pipelines.ingest_excel import ingest_excel
from src.pipelines.ingest_images import ingest_images
from src.reporting.renderer import Renderer

router = APIRouter()


@router.post("/generate", response_model=None)
async def generate_report(
    patient_id: str = Form(...),
    referring_physician: str = Form(default=""),
    output_format: str = Form(default="pdf"),
    excel_file: UploadFile | None = File(default=None),
    image_files: list[UploadFile] = File(default=[]),
):
    """
    Generate a structured medical report from patient data.

    - **excel_file**: Excel file with patient timeline (optional)
    - **image_files**: Medical images JPEG/PNG (optional, multiple)
    - **output_format**: "pdf" | "markdown" | "json"
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Save uploaded files
        excel_path = None
        if excel_file and excel_file.filename:
            excel_path = tmp / excel_file.filename
            excel_path.write_bytes(await excel_file.read())
            logger.info(f"Received Excel: {excel_file.filename}")

        image_paths = []
        for img in image_files:
            if img.filename:
                img_path = tmp / img.filename
                img_path.write_bytes(await img.read())
                image_paths.append(img_path)
                logger.info(f"Received image: {img.filename}")

        # Build request
        request = ReportRequest(
            patient_id=patient_id,
            excel_path=excel_path,
            image_paths=image_paths,
            referring_physician=referring_physician or None,
            output_format=output_format,
        )

        try:
            # Ingest data
            timeline = None
            if excel_path:
                timeline = ingest_excel(excel_path)

            image_metadata = []
            if image_paths:
                image_metadata = ingest_images(image_paths)

            # Run agent
            orchestrator = Orchestrator()
            report: GeneratedReport = await orchestrator.run(
                request=request,
                timeline=timeline,
                images=image_metadata,
            )

            # Render output
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

        except Exception as e:
            logger.exception(f"Report generation failed for {patient_id}")
            raise HTTPException(status_code=500, detail=str(e)) from e


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

    excel_path = Path(case["excel_file"]) if case.get("excel_file") else None
    image_paths = [Path(p) for p in case.get("images", [])]

    request = ReportRequest(
        patient_id=patient_id,
        excel_path=excel_path,
        image_paths=image_paths,
        output_format="json",
    )

    timeline = ingest_excel(excel_path) if excel_path and excel_path.exists() else None
    image_metadata = ingest_images(image_paths) if image_paths else []

    orchestrator = Orchestrator()
    report = await orchestrator.run(request=request, timeline=timeline, images=image_metadata)
    return report.model_dump(mode="json")
