# MedReport AI — Pitch

## Problème

Les médecins radiologues et cliniciens passent en moyenne **30 à 45 minutes** par compte rendu médical.
Avec l'augmentation du volume d'examens (imagerie, biologie, suivi chronologique), cette charge
administrative laisse moins de temps pour la décision clinique.

## Solution

**MedReport AI** est un pipeline agentique qui :

1. **Ingère** les données patient (tableaux Excel de suivi, images médicales)
2. **Analyse** automatiquement l'évolution temporelle et les résultats d'imagerie
3. **Génère** un compte rendu médical structuré, prêt à relire et valider par le médecin

Le médecin passe de la rédaction à la **validation** — gain de temps estimé : 70%.

## Différenciation

| Approche classique | MedReport AI |
|---|---|
| Rédaction manuelle | Génération automatique + validation |
| Silo Excel / PACS | Fusion multi-sources |
| Rapport générique | Personnalisé par type d'examen |
| Aucune tendance | Analyse temporelle automatique |

## Architecture

```
[Excel patient]  [Images DICOM/JPEG]
       │                 │
  ingest_excel      ingest_images
       └────────┬────────┘
            Orchestrator (Claude Agent)
           ┌────┴────────────────────┐
      vision_tool  timeline_tool  report_tool
           └────────┬────────────────┘
                Renderer (PDF / Markdown)
```

## Cas d'usage visé (Hackathon)

- Compte rendu de scanner thoracique (CT-scan)
- Suivi de nodules pulmonaires sur 12 mois
- Rapport de biologie + imagerie combinés

## Stack technique

- **LLM** : Claude Sonnet 4.6 (agents + vision)
- **API** : FastAPI
- **Frontend** : Dashboard Streamlit (bonus)
- **Langage** : Python 3.11
