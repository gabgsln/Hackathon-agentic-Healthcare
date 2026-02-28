# Compte rendu de scanner thoracique

**Patient** : {{ patient.name }} ({{ patient.age }} ans, {{ patient.sex }})
**Date d'examen** : {{ exam_date }}
**Médecin référent** : {{ referring_physician }}
**Généré le** : {{ generated_at }}

---

## 1. Indication clinique

{{ sections.indication }}

---

## 2. Technique d'acquisition

{{ sections.technique }}

---

## 3. Résultats

### 3.1 Parenchyme pulmonaire

{{ sections.parenchyma }}

### 3.2 Médiastin et structures vasculaires

{{ sections.mediastinum }}

### 3.3 Plèvre et paroi thoracique

{{ sections.pleura }}

### 3.4 Structures abdominales hautes (si visible)

{{ sections.upper_abdomen }}

---

## 4. Comparaison avec examens antérieurs

{{ sections.comparison }}

{% if timeline_summary %}
### Évolution chronologique

{{ timeline_summary }}
{% endif %}

---

## 5. Conclusion

{{ sections.conclusion }}

---

## 6. Recommandations

{{ sections.recommendations }}

---

*Compte rendu généré automatiquement par MedReport AI — à valider par un médecin qualifié.*
*Modèle IA : claude-sonnet-4-6 | Pipeline version : {{ pipeline_version }}*
