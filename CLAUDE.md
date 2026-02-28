# CLAUDE.md — Hackathon Agentic Healthcare

## Project Overview
Agentic AI pipeline that ingests medical data (Excel timelines + medical images) and
generates structured radiology / clinical reports using Claude as the orchestration engine.

## Stack
- **Backend**: FastAPI + uvicorn
- **AI**: Anthropic Claude (claude-sonnet-4-6 for agents, claude-opus-4-6 for heavy reasoning)
- **Data**: pandas + openpyxl (Excel), Pillow (images)
- **Reporting**: Jinja2 + WeasyPrint (PDF), Markdown
- **Viz**: Plotly + Streamlit (bonus dashboard)
- **Python**: 3.11+

## Key Commands
```bash
make install    # install dependencies
make dev        # start FastAPI dev server (port 8000)
make dashboard  # start Streamlit dashboard
make test       # run tests
make lint       # ruff + mypy
make demo       # run demo with sample data
```

## Architecture
```
Excel / Images → Pipelines → Orchestrator Agent (Claude + tools) → Renderer → PDF/Markdown Report
```

## Agent Tools
| Tool | Description |
|------|-------------|
| `vision_tool` | Analyze medical images via Claude vision |
| `timeline_tool` | Extract trends from patient timeline |
| `report_tool` | Assemble final structured report |
| `viz_tool` | Generate charts and visualizations |

## Environment
Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

## Data Conventions
- Patient Excel files: one sheet per exam type, columns mapped via `data/schema/`
- Images: DICOM or JPEG/PNG in `data/samples/{patient_id}/images/`
- Anonymized samples: `data/samples/patient_00{1-4}/`

## Code Style
- Ruff for formatting (line-length=100)
- Pydantic v2 for all schemas
- Loguru for logging (no print statements in production code)
- Async FastAPI routes
