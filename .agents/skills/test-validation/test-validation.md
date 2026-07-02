---
name: test-validation
description: Skill de conception et exécution de tests unitaires, d'intégration, de validation croisée et de profilage pour TradingVBT.
---

# Skill : Test & Validation Réelle

Ce skill décrit la méthodologie pour concevoir des tests de manière autonome (indépendamment du code lui-même), vérifier la conformité des modules face aux exigences, et valider que chaque composant donne les résultats attendus avec la tolérance requise.

---

## 1. Méthodologie de Test & Validation

### A. Conception des Tests à Partir des Objectifs
*   **Indépendance** : Les cas de test doivent être rédigés d'après les spécifications et critères de succès définis lors de la planification, sans présupposer de l'implémentation choisie par le Développeur.
*   **Cas Limites (Edge Cases)** : Toujours inclure des tests pour les valeurs nulles, les séries vides, les divisions par zéro, les structures de données désordonnées et les ruptures d'API.
*   **Validation Croisée (Cross-Validation)** : Pour les fonctions ré-implémentées (ex: indicateurs Numba), comparer la sortie face à un tiers de référence (ex: TA-Lib) et affirmer une tolérance stricte (divergence $< 1\text{e-}7$).

### B. Évaluation des Performance et Ressources
*   **Profiling** : Mesurer le temps d'exécution (ex: timeit) et l'empreinte mémoire pour vérifier le respect des benchmarks et l'absence de fuites RAM.

---

## 2. Outils MCP Associés

Pour appliquer ce skill, le Testeur utilise les outils MCP suivants :

### A. VectorBT_PRO (Exécution des tests et comparaison)
*   `VectorBT_PRO/run_code` : Lancer l'exécution des scripts de tests (`pytest`), mesurer les latences d'exécution et profiler l'utilisation mémoire.
*   `VectorBT_PRO/get_source` : Inspecter les variables internes des structures pour vérifier la validité des états après simulation.

### B. Ruflo (Suivi de progression et rapports)
*   `ruflo/progress_check` / `progress_summary` : Générer et suivre la complétion des tests d'intégration continue.

### C. Legacy-skills (Fichiers de tests)
*   `legacy-skills/write_file` : Écrire les scripts de tests unitaires (ex: `tests/test_resampling.py`).
*   `legacy-skills/read_file` : Lire les logs d'erreurs et rapports de couverture générés.
