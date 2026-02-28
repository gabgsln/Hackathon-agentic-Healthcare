# Medical Report Pipeline

A pipeline for generating structured radiology reports from DICOM scans and patient history. It combines deterministic image analysis with an optional LLM enrichment step to produce complete, traceable reports.

DICOM is mandatory — the pipeline refuses to run without it. Excel timelines are optional and only used for patient history, never as a source of lesion measurements.

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add your ANTHROPIC_API_KEY here
```

## Run the full pipeline

```bash
python -m src.pipelines.run_case \
    --dicom  data/raw/patient.dcm \
    --excel  data/raw/history.xlsx \   # optional
    --out    data/processed/CASE_01/ \
    --case-id CASE_01
```

This produces three files:
- `analysis.json` — DICOM metadata, pixel stats, RECIST classification (schema-validated)
- `timeline.json` — patient exam history from Excel (if provided)
- `final_report.md` — the complete Markdown report

If `ANTHROPIC_API_KEY` is set, the pipeline automatically adds a narrative enrichment step (technique description, preliminary findings, conclusions) using `claude-haiku-4-5`. If the key is absent or the API is unreachable, that step is skipped silently and the report still generates.

## Individual pipeline steps

**DICOM analysis only:**
```bash
python -m src.pipelines.dicom_analysis \
    --dicom data/raw/patient.dcm \
    --out   data/processed/analysis.json
```

**Excel ingestion only:**
```bash
python -m src.pipelines.ingest_excel \
    --excel   data/raw/history.xlsx \
    --case-id CASE_01
```

**Report rendering only** (from existing JSON files):
```bash
python -m src.pipelines.generate_report \
    --timeline data/processed/CASE_01_timeline.json \
    --analysis data/processed/CASE_01_analysis.json \
    --out      data/processed/CASE_01_final_report.md
```

## REST API

```bash
make dev   # starts FastAPI on http://localhost:8000
```

Send a `multipart/form-data` POST to `/generate-report` with a `dicom_files` field (required) and optionally `excel_file` and `annotations_json`.

Interactive docs: http://localhost:8000/docs

## How RECIST classification works

The pipeline applies these rules deterministically — no model is involved in the decision:

| Status | Rule |
|--------|------|
| `progression` | Any lesion grows ≥ 20% **and** ≥ 5 mm |
| `response` | Any lesion shrinks ≥ 30% |
| `stable` | Neither threshold reached |
| `unknown` | Single scan — no comparison possible |

## Project layout

```
src/
  pipelines/
    dicom_analysis.py     # pixel_array stats + metadata extraction
    llm_enrichment.py     # optional LLM narrative step (haiku, tool_use)
    run_case.py           # full pipeline entrypoint
    ingest_excel.py       # Excel → timeline JSON
    compute_analysis.py   # RECIST-like analysis
    generate_report.py    # Jinja2 template → Markdown
  imaging/
    dicom_utils.py        # pydicom helpers
    orthanc_utils.py      # Orthanc HTTP API helpers
  agents/
    orchestrator.py       # Claude agent loop
    tools/                # vision, timeline, report, viz tools
  app/
    main.py               # FastAPI application

data/
  schema/
    analysis_schema.json  # JSON Schema (draft-07) for analysis.json

tests/
  test_e2e_pipeline.py    # 18 end-to-end tests
  test_llm_enrichment.py  # 16 enrichment tests (fully mocked)
  test_compute_analysis.py
  test_generate_report.py
  test_parsers.py
  test_ingest_dicom.py
```

## Tests

```bash
make test          # runs all 195 tests
pytest tests/ -v   # same with verbose output
```

Everything runs without a network connection or API key. The LLM enrichment tests mock the Anthropic client entirely.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | No | — | Enables LLM enrichment step |
| `ORTHANC_URL` | No | `http://10.0.1.215:8042` | Orthanc DICOM server |
| `ORTHANC_USER` | No | `unboxed` | Orthanc credentials |
| `ORTHANC_PASS` | No | `unboxed2026` | Orthanc credentials |
