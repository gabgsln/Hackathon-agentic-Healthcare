# Schéma Excel patient attendu

## Feuille : `timeline`

| Colonne | Type | Description |
|---------|------|-------------|
| `date` | date (YYYY-MM-DD) | Date de l'examen / mesure |
| `exam_type` | str | Type d'examen (CT, PET, BIO, RX) |
| `result` | str | Résultat ou valeur mesurée |
| `unit` | str | Unité (mm, HU, mg/L…) |
| `reference_range` | str | Valeur normale (optionnel) |
| `notes` | str | Commentaire clinique (optionnel) |
| `physician` | str | Médecin responsable (optionnel) |

## Feuille : `patient_info`

| Colonne | Type | Description |
|---------|------|-------------|
| `patient_id` | str | Identifiant anonymisé |
| `age` | int | Âge en années |
| `sex` | str | M / F |
| `weight_kg` | float | Poids en kg (optionnel) |
| `height_cm` | float | Taille en cm (optionnel) |
| `smoking_status` | str | Fumeur / Ex-fumeur / Non-fumeur |
| `main_diagnosis` | str | Diagnostic principal |

## Feuille : `nodules` (spécifique thorax)

| Colonne | Type | Description |
|---------|------|-------------|
| `date` | date | Date de mesure |
| `nodule_id` | str | Identifiant du nodule (ex: N1, N2) |
| `location` | str | Lobe / segment |
| `size_mm` | float | Diamètre en mm |
| `density` | str | Solide / Verre dépoli / Mixte |
| `suv_max` | float | SUV max si PET (optionnel) |

## Notes de mapping

Les colonnes peuvent avoir des noms alternatifs — voir `data/schema/column_aliases.json`
pour le mapping entre noms réels et noms canoniques.
