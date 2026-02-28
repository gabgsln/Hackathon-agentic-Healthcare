# Compte rendu de scanner thoracique

*Généré le {{ generated_at }} — Pipeline v{{ pipeline_version }}*

---

## 1. Informations patient

| Champ | Valeur |
|-------|--------|
| Patient ID | `{{ patient_id }}` |
| Nombre d'examens | {{ exam_count }} |
| Premier examen | {{ first_exam_date if first_exam_date else "N/A" }} |
| Dernier examen | {{ last_exam_date if last_exam_date else "N/A" }} |
| Durée de suivi | {% if time_delta_days is not none %}{{ time_delta_days }} jours{% else %}N/A{% endif %} |

---

## 2. Statut global

**{{ overall_status | upper }}**

{% if overall_status == "progression" -%}
Progression documentée selon les critères appliqués :
augmentation ≥ {{ evidence.thresholds.progression_pct }}% ET ≥ {{ evidence.thresholds.progression_abs_mm }} mm sur au moins une lésion.
{%- elif overall_status == "response" -%}
Réponse thérapeutique documentée :
diminution ≥ {{ evidence.thresholds.response_pct }}% sur au moins une lésion.
{%- elif overall_status == "stable" -%}
Maladie stable — aucun critère de progression ou de réponse atteint.
{%- else -%}
Statut indéterminé — données insuffisantes pour évaluation comparative.
{%- endif %}

*Règle appliquée : {{ evidence.rule_applied }}*

---

## 3. Évolution des lésions

{% if lesion_deltas -%}
| # | Référence (mm) | Dernier (mm) | Δ mm | Δ % | Statut |
|---|:--------------:|:------------:|:----:|:---:|--------|
{% for d in lesion_deltas -%}
| {{ d.lesion_index + 1 }} | {% if d.baseline_mm is not none %}{{ d.baseline_mm }}{% else %}—{% endif %} | {% if d.last_mm is not none %}{{ d.last_mm }}{% else %}—{% endif %} | {% if d.delta_mm is not none %}{{ d.delta_mm }}{% else %}—{% endif %} | {% if d.delta_pct is not none %}{{ d.delta_pct }}{% else %}—{% endif %} | {{ d.status }}{% if d.note is defined %} *({{ d.note }})*{% endif %} |
{% endfor %}

- Examen de référence : {{ baseline_exam.date if baseline_exam.date else "N/A" }} (AccessionNumber: `{{ baseline_exam.accession_number if baseline_exam.accession_number else "—" }}`)
- Dernier examen : {{ last_exam.date if last_exam.date else "N/A" }} (AccessionNumber: `{{ last_exam.accession_number if last_exam.accession_number else "—" }}`)
{%- else %}
*Aucune mesure de lésion disponible pour comparaison.*
{%- endif %}

---

## 4. Indicateurs radiologiques

{% set has_kpi = kpi.sum_diameters_baseline_mm is not none or kpi.dominant_lesion_baseline_mm is not none -%}
{% if has_kpi -%}
| Indicateur | Référence | Actuel | Δ |
|------------|:---------:|:------:|:---:|
{% if kpi.sum_diameters_baseline_mm is not none -%}
| Somme des diamètres (mm) | {{ kpi.sum_diameters_baseline_mm }} | {{ kpi.sum_diameters_current_mm if kpi.sum_diameters_current_mm is not none else "—" }} | {{ (kpi.sum_diameters_delta_pct | string + "%") if kpi.sum_diameters_delta_pct is not none else "—" }} |
{% endif -%}
{% if kpi.dominant_lesion_baseline_mm is not none -%}
| Lésion dominante (mm) | {{ kpi.dominant_lesion_baseline_mm }} | {{ kpi.dominant_lesion_current_mm if kpi.dominant_lesion_current_mm is not none else "—" }} | {{ (kpi.dominant_lesion_delta_pct | string + "%") if kpi.dominant_lesion_delta_pct is not none else "—" }} |
{% endif -%}
| Nombre de lésions | {{ kpi.lesion_count_baseline }} | {{ kpi.lesion_count_current }} | {{ kpi.lesion_count_delta }} |
{% if kpi.growth_rate_mm_per_day is not none -%}
| Vitesse de croissance (mm/j) | — | — | {{ kpi.growth_rate_mm_per_day }} |
{% endif -%}
{%- else %}
*Indicateurs non disponibles (données insuffisantes pour comparaison).*
{% endif -%}
| Complétude des données | {{ kpi.data_completeness_score }}% |
|---|---|

---

## 5. Données du dernier rapport

### Information clinique

{{ latest_clinical_information if latest_clinical_information else "*Non disponible.*" }}

### Technique d'acquisition

{{ latest_study_technique if latest_study_technique else "*Non disponible.*" }}

### Résultats

{{ latest_report if latest_report else "*Non disponible.*" }}

### Conclusions

{{ latest_conclusions if latest_conclusions else "*Non disponible.*" }}

---

## 6. Recommandations (déterministes)

{% if overall_status == "progression" -%}
- Consultation oncologique recommandée.
- Réévaluation thérapeutique à envisager.
- Prochain contrôle imaging : 4 semaines.
{%- elif overall_status == "response" -%}
- Poursuite du traitement en cours.
- Prochain contrôle imaging : 3 mois.
{%- elif overall_status == "stable" -%}
- Surveillance radiologique.
- Prochain contrôle imaging : 3–6 mois selon contexte clinique.
{%- else -%}
- Données insuffisantes — bilan complémentaire à envisager.
{%- endif %}

---

## 7. Traçabilité

| Champ | Valeur |
|-------|--------|
| Examen de référence | {{ baseline_exam.date if baseline_exam.date else "N/A" }} |
| Dernier examen | {{ last_exam.date if last_exam.date else "N/A" }} |
| Règle appliquée | {{ evidence.rule_applied }} |
| Seuil progression | ≥ {{ evidence.thresholds.progression_pct }}% ET ≥ {{ evidence.thresholds.progression_abs_mm }} mm |
| Seuil réponse | ≥ {{ evidence.thresholds.response_pct }}% diminution |

---

*Compte rendu généré automatiquement par MedReport AI — à valider par un médecin qualifié.*
*Aucune donnée LLM n'a été utilisée pour ce rapport (pipeline déterministe).*
