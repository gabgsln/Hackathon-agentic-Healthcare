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

## 3. Imaging Findings

{% if dicom_metadata -%}
### Métadonnées DICOM

| Champ | Valeur |
|-------|--------|
| Patient ID | `{{ dicom_metadata.PatientID or "—" }}` |
| Modality | {{ dicom_metadata.Modality or "—" }} |
| Body Part | {{ dicom_metadata.BodyPartExamined or "—" }} |
| Study Date | {{ dicom_metadata.StudyDate or "—" }} |
| Series Description | {{ dicom_metadata.SeriesDescription or "—" }} |
| Instance # | {{ dicom_metadata.InstanceNumber if dicom_metadata.InstanceNumber is not none else "—" }} |
| PixelSpacing (mm) | {% if dicom_metadata.PixelSpacing %}{{ dicom_metadata.PixelSpacing[0] }} × {{ dicom_metadata.PixelSpacing[1] }}{% else %}—{% endif %} |
| SliceThickness (mm) | {{ dicom_metadata.SliceThickness if dicom_metadata.SliceThickness is not none else "—" }} |
| StudyInstanceUID | `{{ dicom_metadata.StudyInstanceUID[:24] if dicom_metadata.StudyInstanceUID else "—" }}…` |
| SeriesInstanceUID | `{{ dicom_metadata.SeriesInstanceUID[:24] if dicom_metadata.SeriesInstanceUID else "—" }}…` |

{% if dicom_image_stats -%}
### Statistiques pixel

| Indicateur | Valeur |
|------------|--------|
| Dimensions | {{ dicom_image_stats.shape | join(" × ") }} px |
| Type de données | {{ dicom_image_stats.dtype }} |
| Min / Max | {{ dicom_image_stats.min }} / {{ dicom_image_stats.max }} |
| Moyenne | {{ dicom_image_stats.mean }} |
| Écart-type | {{ dicom_image_stats.std }} |
| Score de cohérence (0–1) | **{{ dicom_image_stats.data_consistency_score }}** |
{% endif -%}

{%- else %}
*Données DICOM non disponibles pour cet examen.*
{%- endif %}

---

## 4. Calibration & qualité des données

| Champ | Valeur |
|-------|--------|
| Méthode de calibration | {{ calibration.method if calibration.method else "N/A" }} |
| PixelSpacing (mm) | {% if calibration.pixel_spacing_mm %}{{ calibration.pixel_spacing_mm[0] }} × {{ calibration.pixel_spacing_mm[1] }}{% else %}Non disponible{% endif %} |
| Score de complétude | {{ kpi.data_completeness_score }}% |

{% if warnings -%}
### Avertissements

{% for w in warnings -%}
- ⚠️ {{ w }}
{% endfor %}
{%- endif %}

---

## 5. Mesures par imagerie DICOM

{% if studies -%}
{% for study in studies %}
### Examen du {{ study.study_date if study.study_date else "date inconnue" }}

{% if study.lesions -%}
| Lésion | Long. axe (mm) | Court axe (mm) | Coupe | Série |
|--------|:--------------:|:--------------:|:-----:|-------|
{% for l in study.lesions -%}
| {{ l.lesion_id }} | {% if l.long_axis_mm is not none %}{{ l.long_axis_mm }}{% else %}—{% endif %} | {% if l.short_axis_mm is not none %}{{ l.short_axis_mm }}{% else %}—{% endif %} | {{ l.slice_instance if l.slice_instance is not none else "—" }} | `{{ l.series_uid[:16] if l.series_uid else "—" }}…` |
{% endfor %}

**KPIs :** somme axes longs = {{ study.kpis.sum_long_axis_mm if study.kpis.sum_long_axis_mm is not none else "—" }} mm
· lésion dominante = {{ study.kpis.dominant_lesion_mm if study.kpis.dominant_lesion_mm is not none else "—" }} mm
· n = {{ study.kpis.lesion_count }}
{%- else %}
*Aucune lésion annotée pour cet examen.*
{%- endif %}
{% endfor %}
{%- else %}
*Aucune mesure DICOM disponible.*
{%- endif %}

---

## 6. Évolution des lésions (référence → dernier examen)

{% if lesion_deltas -%}
| # | Référence (mm) | Dernier (mm) | Δ mm | Δ % | Statut |
|---|:--------------:|:------------:|:----:|:---:|--------|
{% for d in lesion_deltas -%}
| {{ d.lesion_index + 1 }} | {% if d.baseline_mm is not none %}{{ d.baseline_mm }}{% else %}—{% endif %} | {% if d.last_mm is not none %}{{ d.last_mm }}{% else %}—{% endif %} | {% if d.delta_mm is not none %}{{ d.delta_mm }}{% else %}—{% endif %} | {% if d.delta_pct is not none %}{{ d.delta_pct }}{% else %}—{% endif %} | {{ d.status }}{% if d.note is defined %} *({{ d.note }})*{% endif %} |
{% endfor %}

- Examen de référence : {{ baseline_study.study_date if baseline_study.study_date else "N/A" }}
- Dernier examen : {{ last_study.study_date if last_study.study_date else "N/A" }}
{%- else %}
*Aucun delta calculable (un seul examen ou données insuffisantes).*
{%- endif %}

---

## 7. Indicateurs radiologiques

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
| Complétude des données | {{ kpi.data_completeness_score }}% | | |
|---|---|---|---|

---

## 8. Données du dernier rapport

### Information clinique

{{ latest_clinical_information if latest_clinical_information else "*Non disponible.*" }}

### Technique d'acquisition

{{ latest_study_technique if latest_study_technique else "*Non disponible.*" }}

### Résultats

{{ latest_report if latest_report else "*Non disponible.*" }}

### Conclusions

{{ latest_conclusions if latest_conclusions else "*Non disponible.*" }}

---

## 9. Recommandations (déterministes)

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

## 10. Traçabilité

| Champ | Valeur |
|-------|--------|
| Examen de référence | {{ baseline_study.study_date if baseline_study.study_date else "N/A" }} |
| Dernier examen | {{ last_study.study_date if last_study.study_date else "N/A" }} |
| Règle appliquée | {{ evidence.rule_applied }} |
| Seuil progression | ≥ {{ evidence.thresholds.progression_pct }}% ET ≥ {{ evidence.thresholds.progression_abs_mm }} mm |
| Seuil réponse | ≥ {{ evidence.thresholds.response_pct }}% diminution |
| Méthode mesure | {{ calibration.method if calibration.method else "N/A" }} |
| PixelSpacing (mm) | {% if calibration.pixel_spacing_mm %}{{ calibration.pixel_spacing_mm[0] }} × {{ calibration.pixel_spacing_mm[1] }}{% else %}N/A{% endif %} |

---

*Compte rendu généré automatiquement par MedReport AI — à valider par un médecin qualifié.*
*Les mesures sont dérivées exclusivement des fichiers DICOM (px → mm via PixelSpacing).*
*Aucune mesure Excel n'a été utilisée comme source de taille de lésion.*
