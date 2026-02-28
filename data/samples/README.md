# Données samples

Ce dossier contient des cas patients anonymisés pour tester le pipeline.

## Structure

```
samples/
  patient_001/
    patient_001_timeline.xlsx   # données tabulaires (timeline, nodules, biologie)
    images/
      ct_2024_06.jpg            # coupe CT (anonymisée)
      ct_2025_01.jpg
  patient_002/
    ...
```

## Ajouter un cas

1. Créer un dossier `patient_00X/`
2. Placer le fichier Excel (colonnes selon `data/schema/excel_columns.md`)
3. Placer les images dans `patient_00X/images/` (JPEG ou PNG)
4. Mettre à jour `data/manifests/manifest.json`

## Données réelles

Ne jamais committer de données patient réelles dans ce repo.
Utiliser des données synthétiques ou entièrement anonymisées (pas de nom, date de naissance, etc.).
