---
name: suivi-taches
description: Skill de suivi des tâches, prise de décision, sequential thinking et orchestration des objectifs pour le projet TradingVBT.
---

# Skill : Suivi des Tâches & Orchestration

Ce skill décrit la méthodologie pour organiser la boucle d'exécution (loop) du projet, suivre l'état d'avancement des développements, prendre des décisions architecturales structurées, et diviser les objectifs complexes en sous-tâches claires pour les autres agents.

---

## 1. Méthodologie d'Orchestration

L'orchestrateur suit un cycle continu en 4 étapes pour diriger l'exécution :
1.  **Planification & Décomposition** : Découper le but final en tâches unitaires dépendantes.
2.  **Séquençage & Séquential Thinking** : Analyser les alternatives et valider l'approche logique étape par étape.
3.  **Délégation & Préparation d'Objectifs** : Formuler une feuille de route claire pour l'agent Développeur ou Testeur (expliciter entrées, sorties, et critères de succès de la tâche).
4.  **Audit & Clôture** : Valider les rapports du Testeur pour marquer les tâches terminées et mettre à jour le statut du plan de projet.

---

## 2. Outils MCP Associés

Pour appliquer ce skill, l'Orchestrateur utilise les outils MCP suivants :

### A. Séquential Thinking (Raisonnement Complexe)
*   `sequential-thinking/sequentialthinking` : Ce tool doit être invoqué pour mener des analyses multi-étapes complexes (ex: concevoir la topologie WFO, évaluer les impacts de la liquidation sur la balance, ou résoudre les conflits d'architecture). Il permet d'ajuster le raisonnement de façon dynamique en enregistrant les hypothèses de départ et les corrections.

### B. Ruflo (Suivi des Tâches et Workflows)
*   `ruflo/task_create` : Enregistrer chaque tâche de développement ou de test.
*   `ruflo/task_status` / `task_list` : Inspecter les tâches actives pour piloter la file d'attente.
*   `ruflo/task_complete` : Marquer une tâche résolue après validation finale du Testeur.
*   `ruflo/workflow_create` / `workflow_execute` : Chaîner les pipelines de données et d'optimisation.

### C. Legacy-skills (Persistance locale de l'état)
*   `legacy-skills/read_file` / `read_text_file` : Consulter les plans locaux (`.agents/planning/implementation_plan.md`).
*   `legacy-skills/write_file` / `edit_file` : Mettre à jour l'état d'avancement du projet.
