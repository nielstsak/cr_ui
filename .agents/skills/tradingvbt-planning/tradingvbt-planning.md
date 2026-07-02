---
name: tradingvbt-planning
description: Méthodologie et processus de planification pour concevoir, structurer et valider la liste des tâches du projet TradingVBT à l'aide des outils MCP disponibles.
---

# Skill : Méthodologie de Planification TradingVBT

Ce skill définit la méthodologie formelle pour concevoir, structurer et valider la liste des tâches requises pour le développement de la plateforme **TradingVBT**. Il s'appuie sur l'analyse de documents techniques et l'utilisation des outils de l'écosystème MCP pour concevoir des plans d'implémentation robustes et vérifiables.

---

## 1. Principes Directeurs de Planification

Toute tâche planifiée pour ce projet doit respecter un cadre rigoureux de définition. L'objectif est d'éviter toute ambiguïté technique et de garantir la testabilité réelle de chaque composant avant son passage à l'étape suivante du workflow.

Chaque tâche doit être décrite selon la structure suivante :

```markdown
### Tâche ID : [Nom de la Tâche]
*   **Priorité** : [P0 / P1 / P2]
*   **Dépendances** : [Liste des Tâches ID parentes]
*   **Objectif** : [Description claire du livrable technique et fonctionnel]
*   **Intégration Workflow** : [Entité A (Core) / Entité B (UI) / Ingestion / Pipeline ML / Évaluation]
*   **Entrées & Formats** : [Spécification stricte des variables d'entrée (Numpy dtype, structures, types)]
*   **Sorties & Formats** : [Spécification stricte du format de sortie attendu]
*   **Critère de Succès (Validation Réelle)** : [Protocole de test automatisé et conditions réelles de validation]
```

### Contraintes de Planification & Format de Sortie
*   **AUCUN code ne sera écrit lors de la planification**. L'utilisation d'outils d'exécution (tels que `VectorBT_PRO/run_code`) est exclusivement réservée à l'analyse exploratoire et aux validations de micro-prototypes de recherche.
*   **Format de Sortie à l'issue du Skill** : Le livrable final à l'issue de la planification doit être enregistré localement dans un dossier dédié aux documents de planification, sous le chemin : `.agents/planning/implementation_plan.md` (chemin relatif à la racine du projet). Ce fichier regroupera toutes les tâches organisées selon la structure hiérarchique et le format détaillé prescrits dans ce skill.

---

## 2. Outils MCP Adéquats pour la Planification

Le planificateur doit s'appuyer sur les outils MCP suivants pour documenter et valider les choix techniques durant la phase d'établissement de la liste des tâches :

### A. Serveur MCP : VectorBT_PRO
Ce serveur permet d'explorer et de valider les structures complexes de Vectorbt Pro en Python :
*   `VectorBT_PRO/search` : Chercher dans la documentation de Vectorbt Pro pour vérifier la disponibilité d'APIs spécifiques (ex: Crossed Margin, dynamic resampling).
*   `VectorBT_PRO/find` : Localiser des modules, classes ou méthodes de Vectorbt.
*   `VectorBT_PRO/get_attrs` : Obtenir les attributs et types de propriétés de classes Vectorbt.
*   `VectorBT_PRO/get_source` : Extraire le code source exact d'une fonction ou classe Vectorbt pour s'assurer de sa compatibilité avec Numba JIT (ex: s'assurer qu'aucune boucle critique n'appelle du code Python non compilable).
*   `VectorBT_PRO/run_code` : Exécuter des scripts Python minimalistes de test pour évaluer les performances de resampling, la convergence de calculs de marge ou valider des prototypes d'algorithmes avant planification.

### B. Serveur MCP : legacy-skills (I/O & Workspace)
Ce serveur fournit les outils fondamentaux de manipulation de fichiers dans le workspace :
*   `legacy-skills/read_file` / `read_text_file` : Lire les spécifications techniques (PDF, TXT, JSON) pour en extraire les règles d'intégrité et de calcul.
*   `legacy-skills/write_file` / `edit_file` : Établir et modifier le plan de projet (`implementation_plan.md`) et la liste des tâches (`task.md`).
*   `legacy-skills/list_directory` : Valider la structure de l'arborescence physique locale avant de planifier des tâches de persistence I/O.

### C. Serveur MCP : ruflo (Workflow & Task Coordination)
Ce serveur coordonne le suivi des tâches et le chaînage des composants du projet :
*   `ruflo/task_create` : Initialiser et enregistrer formellement chaque tâche de planification dans le gestionnaire global.
*   `ruflo/task_status` / `task_list` : Suivre l'avancement des développements.
*   `ruflo/task_complete` : Valider et clôturer une tâche lorsque ses critères de succès réels sont atteints.
*   `ruflo/workflow_create` / `workflow_execute` : Modéliser le chaînage d'exécution du pipeline complet (Ingestion REST/WS $\rightarrow$ Resampling $\rightarrow$ Feature Engineering $\rightarrow$ Simulation VBT $\rightarrow$ UI).

---

## 3. Structure Hiérarchique du Plan de Tâches

Le plan d'implémentation doit être organisé en sections et sous-sections logiques respectant les couches architecturales du document SAT (Separation of Responsibilities) :

```markdown
# Phase / Section X : [Nom de la Section]
## Sous-section X.Y : [Composant Architectural]
### Tâche ID1 : [Tâche 1]
...
### Tâche IDN : [Tâche N]
```

Les sections types recommandées pour le projet TradingVBT sont :
1.  **Data-Ops & Persistance** (Ingestion REST/WS, structure HDF5 SWMR, validateur d'intégrité).
2.  **Algo-Core & Indicateurs** (Resampler Numba JIT, Introspection TA-Lib, Factory dynamic VBT, Chunks & LRU RAM Cache).
3.  **ML-Core & Simulation** (Z-Score glissant, Alignement MTF lagging, Target volatilité-ajustée, Portefeuille Crossed Margin, Optuna Multi-Objectif, Drift & Fallback).
4.  **UI & API Gateway** (FastAPI REST endpoints, ZeroMQ / WebSocket IPC bridge, React Frontend, Plotly widgets).
5.  **Quality, DevOps & Deployment** (Tests unitaires / cross-validation VBT vs TA-Lib, Dockerfiles multi-stage CPU/GPU, script d'initialisation).

---

## 4. Protocole de Validation en Conditions Réelles

Chaque critère de succès dans la planification doit décrire une méthode d'évaluation active :
*   **Performance** : Temps d'exécution mesuré via micro-benchmark (ex: temps de resampling de 1M de lignes $< 50\text{ms}$).
*   **Intégrité numérique** : Comparaison absolue avec tolérance fixée (ex: divergence maximale de calcul $< 1\text{e-}7$ par rapport à TA-Lib).
*   **Stabilité des ressources** : Utilisation mémoire surveillée (ex: RAM stable sous le seuil maximal configuré de 8 Go pendant 24h d'ingestion simulée).
*   **Résilience** : Simulation de pannes (ex: déconnexion de 15s sans arrêt critique du WebSocket).
