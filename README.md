# Hackathon-agentic-Healthcare

Agentic AI pipeline that ingests multi-source medical data (Excel timelines + DICOM images)
and automatically generates structured radiology reports using Claude as the orchestration engine.

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Copy environment file and add your Anthropic key
cp .env.example .env

# 4. Start the API
make dev          # FastAPI on http://localhost:8000
make dashboard    # Streamlit dashboard
```

---

## Full pipeline (step by step)

### Step 1 — Ingest Excel

Parse a patient Excel file into a structured timeline JSON:

```bash
python -m src.pipelines.ingest_excel \
    --excel   data/raw/case01.xlsx \
    --case-id CASE_01
# → data/processed/CASE_01_timeline.json

# Optional: explicit sheet name
python -m src.pipelines.ingest_excel \
    --excel   data/raw/case01.xlsx \
    --case-id CASE_01 \
    --sheet   "Sheet1"
```

**Expected Excel columns** (fuzzy-matched, case-insensitive):

| Column | Description |
|--------|-------------|
| `PatientID` | Anonymised patient identifier |
| `AccessionNumber` | Study accession number (links to DICOM) |
| `lesion size in mm` | Measurement(s) — single value, comma/newline-separated |
| `Clinical information data / Pseudo reports` | Free-text report with section markers |

**Output schema** (one object per exam row):

```json
{
  "patient_id": "P001",
  "accession_number": "ACC123",
  "study_date": "2024-06-15",
  "lesion_sizes_mm": [12.5, 14.3],
  "report_raw": "CLINICAL INFORMATION. ...",
  "report_sections": {
    "clinical_information": "...",
    "study_technique": "...",
    "report": "...",
    "conclusions": "..."
  }
}
```

---

### Step 2 — Compute analysis

Deterministic RECIST-like analysis (no LLM):

```bash
python -m src.pipelines.compute_analysis \
    --timeline data/processed/CASE_01_timeline.json
# → data/processed/CASE_01_analysis.json
```

**Rules applied:**

| Status | Criterion |
|--------|-----------|
| `progression` | Any lesion increases ≥ 20% **AND** ≥ 5 mm |
| `response` | Any lesion decreases ≥ 30% |
| `stable` | Neither of the above |
| `unknown` | Fewer than two exams with measurements |

**Output schema:**

```json
{
  "overall_status": "progression",
  "time_delta_days": 182,
  "lesion_deltas": [
    { "lesion_index": 0, "baseline_mm": 10.0, "last_mm": 16.0,
      "delta_mm": 6.0, "delta_pct": 60.0, "status": "progression" }
  ],
  "evidence": {
    "rule_applied": "progression: lesion(s) [0] increased >= 20.0% AND >= 5.0 mm",
    "thresholds": { "progression_pct": 20.0, "progression_abs_mm": 5.0, "response_pct": 30.0 }
  }
}
```

---

### Step 3 — Generate report

Fill the Markdown template deterministically from timeline + analysis:

```bash
python -m src.pipelines.generate_report \
    --timeline data/processed/CASE_01_timeline.json \
    --analysis data/processed/CASE_01_analysis.json \
    --out      data/processed/CASE_01_final_report.md
```

Template: `src/reporting/templates/thorax_report.md` (Jinja2).
No LLM is used — pure template filling.

---

### Step 4 — DICOM enrichment (optional)

Match exams to a local DICOM directory by `AccessionNumber`.
Adds `study_instance_uid`, `series` list, `ct_series_uid`, `seg_series_uid` per exam.
Metadata only — no pixel data loaded.

```bash
python -m src.pipelines.ingest_dicom \
    --timeline  data/processed/CASE_01_timeline.json \
    --dicom-dir /path/to/dicom_root
# → data/processed/CASE_01_timeline_enriched.json
```

---

## Report section markers (case-insensitive, trailing dot optional)

```
CLINICAL INFORMATION.
STUDY TECHNIQUE.
REPORT.
CONCLUSIONS.
```

Missing markers produce `null` for that section.

---

## Project structure

```
src/
  pipelines/
    parsers.py            # parse_lesion_sizes(), split_report_sections()
    ingest_excel.py       # Step 1 — Excel → timeline JSON
    compute_analysis.py   # Step 2 — deterministic RECIST-like analysis
    generate_report.py    # Step 3 — Jinja2 template → Markdown report
    ingest_dicom.py       # Step 4 — DICOM enrichment (optional)
    dicom_utils.py        # low-level DICOM metadata helpers
  agents/
    orchestrator.py       # Claude tool-use agent loop (LLM layer, coming next)
    tools/                # vision, timeline, report, viz tools
  app/
    main.py               # FastAPI application
  reporting/
    templates/
      thorax_report.md    # Jinja2 report template
    renderer.py           # Markdown / PDF renderer

data/
  raw/                    # input Excel files (git-ignored)
  processed/              # output JSON + MD files (git-ignored)
  schema/                 # column documentation
  manifests/              # case manifest

tests/
  test_parsers.py         # parse_lesion_sizes, split_report_sections
  test_compute_analysis.py# deterministic rules + edge cases
  test_generate_report.py # template rendering sanity
  test_ingest_dicom.py    # DICOM utils with mocked datasets
```

---

## Running tests

```bash
make test
# or directly:
python -m pytest tests/ -v
```

---

## Docs

- [Pitch](docs/pitch.md)
- [Architecture](docs/architecture.md)
- [Evaluation grid](docs/evaluation.md)
