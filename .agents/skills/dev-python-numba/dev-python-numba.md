---
name: dev-python-numba
description: Skill de développement Python hautement optimisé (Numba JIT, buffers NumPy contigus) et intégration de Vectorbt Pro.
---

# Skill : Développement Python & Numba (TradingVBT)

Ce skill détaille les directives de codage, de performance, et de compilation JIT à respecter pour écrire le code source de la plateforme. Le développeur doit écrire un maximum de **1 fichier par requête** afin de garantir la qualité et la conformité du code.

---

## 1. Directives de Codage & Optimisation

### A. Numba JIT (No-Python Mode)
*   **Compilation stricte** : Toutes les fonctions critiques d'agrégation, de calcul d'indicateurs personnalisés, de PnL et de liquidation doivent utiliser le décorateur `@numba.njit(nogil=True, parallel=False)`.
*   **Pas d'Object Fallback** : Le mode Object-Mode (fallback Python) est strictement interdit. Toutes les variables et structures de données manipulées dans les boucles JIT doivent être compilables de façon statique.
*   **Structures intermédiaires** : Éviter d'allouer de la mémoire dans les boucles JIT ; utiliser des arrays Numpy pré-alloués passés en paramètres si possible.

### B. Gestion des Arrays NumPy
*   **Buffers Contigus** : Garantir que les buffers d'entrée sont en mémoire contiguë (C-contiguous, dtype uniforme) pour maximiser le cache processeur et le SIMD.
*   **Types Strict** : Respecter les dtypes `float64` pour le calcul, `int64` pour les timestamps et index temporels, `int32` pour les compteurs discrets.

---

## 2. Outils MCP Associés

Pour appliquer ce skill, le Développeur utilise les outils MCP suivants :

### A. VectorBT_PRO (API Exploration & Testing)
*   `VectorBT_PRO/get_source` : Extraire le code source des fonctions de Vectorbt Pro pour copier les bonnes pratiques de signatures Numba JIT de la librairie.
*   `VectorBT_PRO/get_attrs` : Vérifier les attributs de classes vectorbt complexes (ex: `Portfolio`, `IndicatorFactory`) avant écriture.
*   `VectorBT_PRO/run_code` : Valider les syntaxes NumPy/Numba et mesurer les performances des fonctions sur des échantillons réduits (micro-benchmarking).

### B. Legacy-skills (Édition de code)
*   `legacy-skills/write_file` / `edit_file` : Créer et modifier le code source de l'application (ex: `fast_resample.py`, `cross_margin_sim.py`) à raison de 1 fichier à la fois.
*   `legacy-skills/read_file` : Consulter les plans locaux pour aligner l'écriture sur les variables d'entrées/sorties planifiées.
