# Grille d'évaluation — MedReport AI

## Critères hackathon

### 1. Pertinence médicale (30 pts)
- [ ] Le rapport généré contient les sections standards d'un compte rendu radiologique
- [ ] Les conclusions sont cohérentes avec les données ingérées
- [ ] L'évolution temporelle est correctement interprétée
- [ ] Les images sont correctement décrites

### 2. Qualité technique (25 pts)
- [ ] Pipeline bout-en-bout fonctionnel (Excel + images → PDF)
- [ ] Agent loop avec au moins 2 tools appelés
- [ ] API FastAPI opérationnelle
- [ ] Code propre, typé, testé

### 3. Innovation / UX (20 pts)
- [ ] Dashboard de visualisation (bonus)
- [ ] Différenciation vs approche naïve (simple prompt)
- [ ] Qualité du rendu final (PDF/Markdown)

### 4. Robustesse (15 pts)
- [ ] Gestion des erreurs (fichier manquant, format invalide)
- [ ] Tests unitaires présents
- [ ] Pas de données patient réelles

### 5. Présentation (10 pts)
- [ ] Pitch clair en < 5 minutes
- [ ] Démo live fonctionnelle
- [ ] Cas d'usage bien défini

## Total : 100 pts

---

## Métriques de qualité du rapport (auto-évaluation)

| Critère | Méthode de mesure |
|---------|-------------------|
| Complétude | % sections remplies / template |
| Cohérence | Score LLM-as-judge (Claude) |
| Précision temporelle | Comparaison timeline vs conclusions |
| Temps de génération | < 60s pour un rapport complet |

## Limites connues

- Les rapports générés **doivent être validés** par un médecin
- L'analyse d'image est basée sur la vision LLM, non sur des modèles radiologiques spécialisés
- Les données d'entraînement de Claude peuvent introduire des biais
- Pas de certification médicale (dispositif de classe I usage démonstration uniquement)
