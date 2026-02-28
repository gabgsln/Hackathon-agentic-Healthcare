# 🏥 Hackathon Agentic Healthcare

## 🚀 Overview

This project is an end-to-end medical imaging pipeline designed for hackathons and research demos. It takes real DICOM medical images (CT/MR), extracts structured data, optionally integrates clinical timelines, and automatically generates a clinical-style report.

The goal is to demonstrate a transparent, deterministic, and explainable AI workflow for healthcare — not a black-box model.

---

## 🧠 What the Project Does

This system transforms raw medical imaging data into structured clinical insights through a reproducible pipeline:

**Input:**

* Mandatory: `.dcm` (DICOM medical image or series)
* Optional: `.xlsx` (patient timeline / lesion measurements)

**Output:**

* `analysis.json` → Structured, schema-validated imaging analysis
* `timeline.json` → Parsed patient history (if Excel provided)
* `final_report.md` → Auto-generated clinical report (10 sections)

---

## 🏗️ Project Architecture

```
src/
  pipelines/           # Core deterministic pipeline
    dicom_analysis.py  # Reads DICOM → metadata + pixel stats
    compute_analysis.py# RECIST logic (pure math, deterministic)
    ingest_excel.py    # Excel → structured timeline JSON
    generate_report.py # Jinja2 → Markdown report
    llm_enrichment.py  # Optional narrative enrichment (non-critical)
    run_case.py        # Main entrypoint (orchestrates full pipeline)

  imaging/
    dicom_utils.py     # pydicom helpers (spacing, slices, metadata)
    orthanc_utils.py   # Orthanc PACS integration (optional)

  agents/
    orchestrator.py    # Conversational agent loop (tool-based)
    tools/             # Vision, timeline, report utilities

  app/
    main.py            # FastAPI backend
    routes/            # API endpoints (report generation)

  reporting/
    templates/
      thorax_report.md # 10-section clinical report template

data/
  raw/                 # Input DICOM / Excel
  processed/           # Generated outputs per case
  schema/
    analysis_schema.json # JSON schema validation (draft-07)

tests/                 # Full unit + E2E test suite
```

---

## 🔬 How the Pipeline Works (Step-by-Step)

### 1. DICOM Ingestion (Mandatory)

`dicom_analysis.py`

* Reads `.dcm` file or DICOM series
* Extracts:

  * PatientID
  * Modality (CT, MR, etc.)
  * PixelSpacing
  * SliceThickness
  * Image shape
  * Min / Max / Mean / Std
  * Data consistency score

Outputs: `analysis.json` (schema validated)

---

### 2. Schema Validation (Hard Safety Step)

All outputs are validated against:

```
data/schema/analysis_schema.json
```

If validation fails → pipeline stops (no silent errors).

---

### 3. Optional LLM Enrichment (Safe & Isolated)

`llm_enrichment.py`

* Adds narrative text (findings, technique, summary)
* NEVER modifies:

  * KPIs
  * RECIST status
  * DICOM metadata
  * Clinical calculations

This keeps the pipeline medically deterministic.

---

### 4. Clinical Timeline Integration (Optional)

`ingest_excel.py`

* Parses Excel patient history
* Extracts:

  * Exam dates
  * Lesion sizes
  * Clinical notes

Outputs: `timeline.json`

---

### 5. Deterministic RECIST Analysis

`compute_analysis.py`

* Pure mathematical logic
* No LLM
* Computes:

  * Lesion deltas
  * Time progression
  * Overall status (e.g. Stable, Progression, Unknown)

Important: If only a single DICOM slice is provided, status may be `unknown` due to insufficient longitudinal data. This is expected clinical behavior.

---

### 6. Automated Report Generation

`generate_report.py`

* Uses Jinja2 template
* Priority for textual sections:

```
Excel Timeline > LLM Enrichment > "Non disponible"
```

Outputs:

* `final_report.md` (clinical-style Markdown report)

---

## 📊 Example Data Flow

```
.dcm file
   ↓
dicom_analysis.py
   ↓
analysis.json (validated)
   ↓
(+ optional Excel)
   ↓
timeline.json
   ↓
generate_report.py
   ↓
final_report.md
```

---

## 🧪 Testing & Reliability

The project includes a full test suite:

* 18 End-to-End pipeline tests
* LLM enrichment tests (fully mocked)
* Parser tests
* DICOM ingestion tests
* Report generation tests

Run all tests:

```bash
pytest tests/
```

---

## ⚙️ Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd Hackathon-agentic-Healthcare
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## ▶️ How to Run the Pipeline (Demo Command)

Single case execution:

```bash
python -m src.pipelines.run_case \
  --case-id CASE_001 \
  --dicom path/to/file_or_folder \
  --xlsx path/to/timeline.xlsx
```

Outputs will be generated in:

```
data/processed/CASE_001/
```

Containing:

* `analysis.json`
* `timeline.json` (if provided)
* `final_report.md`

---

## 🌐 API (FastAPI Backend)

Start the server:

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

Main endpoint:

```
POST /generate-report
```

This endpoint:

* Accepts DICOM + optional Excel
* Runs full pipeline
* Returns structured analysis + report

---

## 🧷 Important Notes (Medical Data)

* PNG/JPG screenshots are NOT suitable for medical analysis
* Only original DICOM (.dcm) files preserve:

  * Physical spacing
  * Hounsfield Units (CT)
  * Metadata integrity

The pipeline is designed for real medical imaging workflows (PACS / Orthanc compatible).

---



## 🔮 Future Improvements

* Automatic lesion segmentation (DICOM SEG support)
* 3D volumetric analysis
* PDF clinical report export
* Frontend dashboard (Next.js)
* Multi-exam longitudinal tracking

---

## 👨‍⚕️ Disclaimer

This project is for research and hackathon demonstration purposes only.
It is NOT a medical device and must not be used for clinical diagnosis.

---

## 📜 License

MIT License (or specify your preferred license)
