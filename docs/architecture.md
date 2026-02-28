# Architecture — MedReport AI

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI (:8000)                       │
│   POST /report/generate    GET /health                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │   Orchestrator  │  ← Claude claude-sonnet-4-6 + tool_use
              │   (agent loop)  │
              └────────┬────────┘
         ┌─────────────┼─────────────┐
         │             │             │
   ┌─────▼─────┐ ┌─────▼──────┐ ┌───▼──────────┐
   │vision_tool│ │timeline_   │ │ report_tool  │
   │(imagerie) │ │tool (Excel)│ │ (assemblage) │
   └─────┬─────┘ └─────┬──────┘ └───┬──────────┘
         │             │             │
   ┌─────▼─────────────▼─────────────▼──────────┐
   │              Renderer                        │
   │        Markdown / PDF (WeasyPrint)           │
   └──────────────────────────────────────────────┘
```

## Flux de données

### 1. Ingestion
- `ingest_excel.py` : lit le fichier Excel patient → construit une timeline structurée (JSON)
- `ingest_images.py` : lit les images (JPEG/PNG/DICOM) → extrait métadonnées + thumbnails base64

### 2. Orchestration (Agent Loop)
L'orchestrateur reçoit un `ReportRequest` et lance une boucle agentique :
```
system_prompt + patient_context
    → Claude [think]
    → tool_call: timeline_tool(timeline_json)
    → tool_call: vision_tool(image_b64)
    → tool_call: report_tool(sections)
    → final_report (text)
```

### 3. Rendu
`renderer.py` prend le rapport texte + template Jinja2 et produit :
- `report.md` — Markdown lisible
- `report.pdf` — PDF via WeasyPrint

### 4. API (optionnel)
`POST /report/generate` accepte un `multipart/form-data` (Excel + images)
et retourne le PDF ou JSON selon `Accept` header.

## Modules

| Module | Rôle |
|--------|------|
| `src/core/config.py` | Settings Pydantic (env vars) |
| `src/core/types.py` | Schémas de données partagés |
| `src/pipelines/ingest_excel.py` | Parser Excel → PatientTimeline |
| `src/pipelines/ingest_images.py` | Parser images → ImageMetadata |
| `src/agents/orchestrator.py` | Boucle agentique principale |
| `src/agents/tools/vision_tool.py` | Analyse d'image via Claude vision |
| `src/agents/tools/timeline_tool.py` | Résumé de tendances chronologiques |
| `src/agents/tools/report_tool.py` | Assemblage du compte rendu |
| `src/agents/tools/viz_tool.py` | Génération de graphiques Plotly |
| `src/reporting/renderer.py` | Rendu Markdown / PDF |
| `src/viz/dashboard.py` | Dashboard Streamlit interactif |
| `src/app/main.py` | Point d'entrée FastAPI |

## Décisions techniques

- **Claude tool_use** plutôt qu'un framework agent externe → contrôle total, moins de dépendances
- **Pydantic v2** pour tous les schémas → validation stricte + sérialisation JSON rapide
- **WeasyPrint** pour le PDF → rendu HTML/CSS → meilleure personnalisation que reportlab
- **Streamlit** pour le dashboard → démo rapide sans frontend séparé
