# Plan d'Implémentation Technique - TradingVBT

Ce document présente la planification technique détaillée et structurée pour le développement de la plateforme **TradingVBT**. Les 84 tâches unitaires issues du référentiel d'exécution technique ont été consolidées en **60 tâches techniques cohérentes** (respectant la cible de 50 à 80 tâches demandée), éliminant les redondances tout en préservant l'intégralité des spécifications fonctionnelles, mathématiques et DevOps.

---

## 1. Principes d'Ingénierie et de Validation
Toutes les tâches planifiées respectent une séparation stricte des responsabilités (SoC) entre le **Core Engine (Entité A)** et le **Layer UI (Entité B)**.
Aucun biais d'anticipation (look-ahead bias) n'est toléré. Toutes les structures NumPy et formats de fichiers HDF5 sont typés explicitement à l'écriture pour maximiser les performances de calcul vectorisé sous Numba et Vectorbt Pro.

---

# Section 1 : Data-Ops & Persistance (Ingestion)

## Sous-section 1.1 : Infrastructure HDF5/Zarr

### Tâche T01 : Initialisation de la Structure et de l'Environnement de Stockage HDF5
*   **Priorité** : P0
*   **Dépendances** : Aucune
*   **Objectif** : Configurer l'environnement de développement Conda isolé, installer les dépendances critiques (`numpy`, `h5py`, `vectorbtpro`, `numba`, `optuna`), et créer l'arborescence de stockage physique pour la persistance locale.
*   **Intégration Workflow** : Ingestion / Core
*   **Entrées & Formats** : Fichier de configuration d'environnement `environment.yml` ; chemins d'accès sous forme de chaînes de caractères.
*   **Sorties & Formats** : Environnement Conda actif ; répertoires créés sous la forme `/data/{exchange}/{symbol}/{timeframe}`.
*   **Critère de Succès (Validation Réelle)** : Environnement créé sans conflit de dépendances. Test d'écriture binaire brute mesurant un débit d'écriture supérieur à 50 Mo/s sur SSD NVMe avec un taux de compression supérieur à 1,5x.

### Tâche T02 : Schéma et Validation du Typage Strict OHLCV
*   **Priorité** : P0
*   **Dépendances** : T01
*   **Objectif** : Implémenter et forcer le schéma de typage strict des données financières lors de l'écriture dans les fichiers HDF5 pour éviter les conversions coûteuses en RAM.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Données de bougies brutes sous forme de dictionnaires ou de DataFrames Pandas.
*   **Sorties & Formats** : Colonnes HDF5 typées : `open_time` (int64 ms), `open` (float64), `high` (float64), `low` (float64), `close` (float64), `volume` (float64), `quote_vol` (float64), `trades` (int32).
*   **Critère de Succès (Validation Réelle)** : Rejet systématique à l'écriture de tout format non-conforme (ex: timestamps float ou non-ms). Acceptation des volumes à 0.0 et rejet des valeurs négatives via assertion pré-écriture. Vérification qu'aucun downcast en float32 n'est appliqué sur le disque.

### Tâche T03 : Indexation Temporelle Primaire et Slicing O(1)
*   **Priorité** : P0
*   **Dépendances** : T02
*   **Objectif** : Créer un index temporel primaire sur la colonne `open_time` pour permettre des opérations de fenêtrage et de lecture ciblée instantanées.
*   **Intégration Workflow** : Ingestion / Core
*   **Entrées & Formats** : Fichier HDF5 structuré.
*   **Sorties & Formats** : Index HDF5 indexé et ordonné de manière strictement monotone croissante.
*   **Critère de Succès (Validation Réelle)** : Exécution de requêtes de slicing temporel du type `data[t1:t2]` s'exécutant en complexité temporelle $O(1)$.

### Tâche T04 : Gestionnaire de Verrous de Concurrence (File Locking)
*   **Priorité** : P0
*   **Dépendances** : T02
*   **Objectif** : Implémenter un mécanisme de file locking pour gérer les accès concurrents en lecture/écriture sur les fichiers HDF5 entre le Core Engine et le processus d'ingestion.
*   **Intégration Workflow** : Ingestion / Core
*   **Entrées & Formats** : Descripteurs de fichiers système HDF5.
*   **Sorties & Formats** : Verrous logiques ou verrous exclusifs (SWMR - Single Writer Multiple Reader).
*   **Critère de Succès (Validation Réelle)** : Simulation d'accès simultanés : lancement de 10 processus de lecture intensifs pendant qu'un processus écrit en continu sans lever d'exception de corruption ou de blocage.

### Tâche T05 : Wrapper d'Abstraction I/O
*   **Priorité** : P0
*   **Dépendances** : T03, T04
*   **Objectif** : Concevoir une classe d'interface Python masquant les appels de bas niveau à la bibliothèque `h5py` et exposant uniquement les méthodes sécurisées de lecture et d'écriture par blocs.
*   **Intégration Workflow** : Ingestion / Core
*   **Entrées & Formats** : `append_chunk(numpy.ndarray)` et `read_chunk(t_start, t_end)`.
*   **Sorties & Formats** : NumPy structured array pour la lecture.
*   **Critère de Succès (Validation Réelle)** : Aucun import ou appel direct à `h5py` en dehors de la classe wrapper. Tous les tests d'écriture/lecture passent via le wrapper.

### Tâche T06 : Outil de Scan et de Validation d'Intégrité
*   **Priorité** : P1
*   **Dépendances** : T05
*   **Objectif** : Développer un utilitaire en ligne de commande pour scanner les fichiers HDF5 et détecter les blocs de données corrompus ou les valeurs NaN non gérées.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Chemin du dossier de stockage des données.
*   **Sorties & Formats** : Rapport d'intégrité JSON ; code de retour Unix (0 si sain, 1 si corrompu).
*   **Critère de Succès (Validation Réelle)** : Détection immédiate d'un NaN injecté artificiellement dans un fichier de test et retour du code d'erreur 1.

---

## Sous-section 1.2 : Connecteurs API (Binance)

### Tâche T07 : Client HTTP Asynchrone Sécurisé avec Signature HMAC
*   **Priorité** : P0
*   **Dépendances** : T01
*   **Objectif** : Implémenter un client HTTP asynchrone performant utilisant `aiohttp` pour l'interfaçage avec l'API REST de Binance, incluant la génération de signatures HMAC-SHA256 pour les requêtes authentifiées.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Clés API / Secret (chaînes de caractères) ; paramètres de requêtes (dictionnaires).
*   **Sorties & Formats** : Réponses JSON brutes.
*   **Critère de Succès (Validation Réelle)** : Négociation TLS 1.3 établie avec Keep-Alive actif ; requêtes signées acceptées par Binance sans erreur 401.

### Tâche T08 : Pagination de l'Historique et Résolveur de Timestamps Différentiels
*   **Priorité** : P0
*   **Dépendances** : T07
*   **Objectif** : Créer un moteur de pagination robuste pour télécharger l'historique complet des bougies par blocs de 1000, calculant dynamiquement le prochain timestamp (`start_time = local_last + 1ms`) pour éviter les trous ou les chevauchements.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : `symbol` (str), `timeframe` (str), `start_timestamp` (int64 ms).
*   **Sorties & Formats** : Flux de listes JSON représentant les bougies historiques.
*   **Critère de Succès (Validation Réelle)** : Téléchargement complet et sans interruption de 5 ans d'historique 5min pour une paire cible sans erreur d'allocation mémoire ni chevauchement de bougies.

### Tâche T09 : Normaliseur de Payloads JSON Binance
*   **Priorité** : P0
*   **Dépendances** : T08
*   **Objectif** : Développer un module de parsing rapide convertissant les structures JSON complexes renvoyées par Binance vers le format NumPy structuré requis par la base de données HDF5.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Payload JSON brut de Binance.
*   **Sorties & Formats** : NumPy structured array conforme au schéma validé en T02.
*   **Critère de Succès (Validation Réelle)** : Temps d'exécution du parsing de normalisation inférieur à 5 ms pour un bloc de 1000 bougies.

### Tâche T10 : Rate Limiter de Quotas API et Kill Switch
*   **Priorité** : P0
*   **Dépendances** : T07
*   **Objectif** : Gérer activement les limites de requêtes imposées par Binance en lisant l'en-tête `X-MBX-USED-WEIGHT-1M` et en implémentant un coupe-circuit (Kill Switch) en cas de code HTTP 418 ou 429.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : En-têtes HTTP des réponses reçues.
*   **Sorties & Formats** : Suspension temporaire (pause) des coroutines d'appel API.
*   **Critère de Succès (Validation Réelle)** : Pause automatique des requêtes dès que le poids consommé atteint 80% du quota autorisé. Suspension immédiate de tout appel et respect du délai `Retry-After` en cas d'interception d'un code 429.

### Tâche T11 : Gestionnaire d'Erreurs Réseau et Algorithme de Relance (Backoff)
*   **Priorité** : P1
*   **Dépendances** : T07
*   **Objectif** : Mettre en œuvre une stratégie de résilience face aux pannes d'API Binance ou de réseau en utilisant un algorithme de backoff exponentiel avec gigue.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Exceptions HTTP et Timeouts (aiohttp).
*   **Sorties & Formats** : Tentatives de reconnexion temporisées.
*   **Critère de Succès (Validation Réelle)** : Simulation de coupure réseau : interruption artificielle de 15s gérée automatiquement sans arrêt du processus principal (maximum de 3 tentatives de relance).

---

## Sous-section 1.3 : Flux Temps Réel (WebSockets)

### Tâche T12 : Client WebSocket Persistant et Gestion des Abonnements
*   **Priorité** : P0
*   **Dépendances** : T01
*   **Objectif** : Implémenter une connexion WebSocket asynchrone permanente avec le serveur de flux Binance pour écouter les ticks en temps réel, avec la possibilité d'ajouter ou de retirer dynamiquement des paires de trading du flux d'écoute.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : URI du flux (`wss://stream.binance.com:9443/ws`) ; messages de contrôle JSON (SUBSCRIBE/UNSUBSCRIBE).
*   **Sorties & Formats** : Stream asynchrone de payloads JSON de ticks.
*   **Critère de Succès (Validation Réelle)** : Connexion maintenue active pendant 24 heures sans déconnexion non gérée, avec envoi et réception automatique de Pings/Pongs.

### Tâche T13 : Cache Volatile RAM à Haute Performance
*   **Priorité** : P0
*   **Dépendances** : T12
*   **Objectif** : Stocker temporairement en mémoire vive les ticks entrants des bougies en cours de formation (`x: false` dans le flux Binance) pour un accès à latence ultra-faible.
*   **Intégration Workflow** : Ingestion / UI
*   **Entrées & Formats** : Payload JSON du tick en temps réel.
*   **Sorties & Formats** : Structure de données circulaire en RAM accessible en lecture/écriture.
*   **Critère de Succès (Validation Réelle)** : Latence de mise à jour et de lecture dans le cache RAM inférieure à 1 ms.

### Tâche T14 : Détecteur de Clôture de Bougie et Écriture Atomique HDF5
*   **Priorité** : P0
*   **Dépendances** : T05, T13
*   **Objectif** : Détecter l'indicateur de fin de bougie (`x: true`) dans le flux WebSocket pour déclencher immédiatement l'écriture de la bougie finalisée dans le fichier HDF5 persistant.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Payload WebSocket du tick de clôture.
*   **Sorties & Formats** : Requête d'écriture asynchrone HDF5.
*   **Critère de Succès (Validation Réelle)** : Écriture instantanée de la bougie dans le HDF5 à la seconde précise de sa clôture sur l'échange.

### Tâche T15 : Watchdog WebSocket et Réconciliation REST (Gap Fill)
*   **Priorité** : P1
*   **Dépendances** : T08, T12, T14
*   **Objectif** : Implémenter un chien de garde (Watchdog) pour surveiller le flux WebSocket. En cas de silence radio supérieur à 3 minutes, forcer la reconnexion et interroger l'API REST pour récupérer et insérer les bougies manquées.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Timestamps système ; requêtes de réconciliation REST.
*   **Sorties & Formats** : Insertion des données de réconciliation dans HDF5.
*   **Critère de Succès (Validation Réelle)** : Interruption volontaire du WebSocket pendant 5 minutes : reconnexion automatique réussie et comblement complet du trou de données (gap) dans le fichier HDF5 sans aucune duplication.

---

# Section 2 : Algo-Core & Indicateurs

## Sous-section 2.1 : Resampling JIT (Numba)

### Tâche T16 : Environnement de Compilation Numba et Pré-allocation Mémoire
*   **Priorité** : P0
*   **Dépendances** : T01
*   **Objectif** : Configurer la compilation `@njit(nogil=True)` et implémenter l'algorithme d'allocation prédictive de taille de tableau pour éviter les redimensionnements dynamiques en cours de boucle.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Tableaux NumPy 1D (timestamps int64, prix float64) ; fréquence cible (int64 ms).
*   **Sorties & Formats** : Tableaux NumPy pré-alloués de dimension fixe `(T_end - T_start) // target_period_ms`.
*   **Critère de Succès (Validation Réelle)** : Compilation réussie en mode "No-Python" pur. Aucune alerte de type "Python Object Fallback" dans le rapport de compilation Numba.

### Tâche T17 : Algorithme JIT d'Agrégation OHLCV
*   **Priorité** : P0
*   **Dépendances** : T16
*   **Objectif** : Écrire le cœur mathématique de l'agrégateur JIT pour calculer les valeurs de bougies de fréquences supérieures à partir des données sources de base.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Données brutes sous forme de tableaux NumPy (open, high, low, close, volume).
*   **Sorties & Formats** : Tuple de tableaux NumPy agrégés.
*   **Critère de Succès (Validation Réelle)** : Validation par tests unitaires que :
    $$Open_j = Open_{i_{start}}, \quad High_j = \max(High_{i_{start}..i_{end}}), \quad Low_j = \min(Low_{i_{start}..i_{end}}), \quad Close_j = Close_{i_{end}}$$
    et
    $$Volume_j = \sum_{k=i_{start}}^{i_{end}} Volume_k$$

### Tâche T18 : Traitement des Gaps de Cotation (Forward Fill / Zero Fill)
*   **Priorité** : P0
*   **Dépendances** : T17
*   **Objectif** : Gérer les périodes d'inactivité du marché en appliquant une règle de forward-fill sur les prix (propagation du dernier cours de clôture) et de zero-fill sur les volumes.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Tableaux NumPy de bougies resamplées contenant des périodes vides.
*   **Sorties & Formats** : Tableaux NumPy propres sans NaN.
*   **Critère de Succès (Validation Réelle)** : Pour chaque bougie sans transaction : validation que $O_j = H_j = L_j = C_j = C_{j-1}$ et $V_j = 0.0$.

### Tâche T19 : Alignement Temporel et Support des Fréquences Multiples
*   **Priorité** : P0
*   **Dépendances** : T18
*   **Objectif** : Définir l'index temporel des bougies agrégées sur leur heure de clôture (Close Time) et assurer le bon fonctionnement du resampler pour toute fréquence arbitraire ($N \times Base\_Freq$).
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Timestamps (int64 ms) ; facteur d'échelle temporel (ex: 7min, 45min, 4h).
*   **Sorties & Formats** : Index temporel de sortie aligné causalement.
*   **Critère de Succès (Validation Réelle)** : Validation de l'alignement temporel des indicateurs. Calcul correct et sans erreur des bougies sur des fréquences non standards.

### Tâche T20 : Optimisation CPU de la Boucle Critique de Resampling
*   **Priorité** : P1
*   **Dépendances** : T17
*   **Objectif** : Profiler et optimiser la boucle d'agrégation JIT pour s'assurer qu'elle traite très rapidement les flux de données historiques volumineux.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Tableaux de test NumPy contenant 1 000 000 de lignes.
*   **Sorties & Formats** : Données resamplées optimisées.
*   **Critère de Succès (Validation Réelle)** : Temps d'exécution du resampling complet de 1M de lignes inférieur à 50 ms sur un seul cœur CPU.

---

## Sous-section 2.2 : TA-Lib Factory & Introspection

### Tâche T21 : Introspection Dynamique de l'API C de TA-Lib
*   **Priorité** : P1
*   **Dépendances** : T01
*   **Objectif** : Parcourir par programmation les signatures C de la bibliothèque TA-Lib pour extraire automatiquement les types d'entrées, de sorties et de paramètres des indicateurs.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Fonctions exportées par `talib.get_functions()`.
*   **Sorties & Formats** : Catalogue structuré des indicateurs (dictionnaire Python).
*   **Critère de Succès (Validation Réelle)** : Génération complète de la liste des indicateurs supportés avec typage correct sans intervention manuelle.

### Tâche T22 : Traducteur de Paramètres pour l'UI
*   **Priorité** : P1
*   **Dépendances** : T21
*   **Objectif** : Traduire les signatures d'indicateurs extraites en schémas de données JSON pour permettre à l'UI de construire dynamiquement les formulaires d'ajustement de paramètres.
*   **Intégration Workflow** : Entité B (UI)
*   **Entrées & Formats** : Catalogue d'indicateurs (T21).
*   **Sorties & Formats** : Schémas JSON standardisés (ex: type entier avec bornes [2..100] traduit en Slider).
*   **Critère de Succès (Validation Réelle)** : Rendu automatique dans l'interface d'un composant de formulaire adapté à chaque paramètre d'indicateur à partir du schéma JSON.

### Tâche T23 : Wrapper IndicatorFactory de Vectorbt Pro
*   **Priorité** : P0
*   **Dépendances** : T21
*   **Objectif** : Encapsuler les appels de fonctions TA-Lib compilées dans une classe usine héritant de `vbt.IndicatorFactory` pour générer dynamiquement des indicateurs compatibles avec les calculs vectorisés de Vectorbt.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Fonctions d'exécution d'indicateurs personnalisées.
*   **Sorties & Formats** : Classes générées héritant de `vbt.Indicator`.
*   **Critère de Succès (Validation Réelle)** : Création et exécution réussie d'une classe d'indicateur dynamique (ex: `DynamicTALib`) sans compilation manuelle intermédiaire.

### Tâche T24 : Validateur de Broadcasting NumPy Multidimensionnel
*   **Priorité** : P0
*   **Dépendances** : T23
*   **Objectif** : S'assurer du bon comportement de la diffusion de dimensions (broadcasting) lors de l'application de grilles de paramètres volumineuses sur des indicateurs vectorisés.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Vecteur de données 1D et vecteur de paramètres 1D.
*   **Sorties & Formats** : Matrice NumPy 2D (Taille: échantillon x combinaisons).
*   **Critère de Succès (Validation Réelle)** : Expansion dimensionnelle réussie ; calcul de l'indicateur sur toutes les colonnes de paramètres s'exécutant sans boucle Python lente.

### Tâche T25 : Chunking Paramétrique de Protection RAM
*   **Priorité** : P1
*   **Dépendances** : T24
*   **Objectif** : Mettre en œuvre une logique de division par blocs (chunking) pour segmenter l'espace des paramètres lors de simulations combinatoires très lourdes afin de prévenir les débordements de mémoire vive (RAM).
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Paramètre de limite de taille de chunk en mémoire.
*   **Sorties & Formats** : Blocs d'évaluation séquentiels.
*   **Critère de Succès (Validation Réelle)** : Simulation de 10 millions de combinaisons s'exécutant complètement par sous-blocs sans provoquer de panne `MemoryError`.

### Tâche T26 : Générateur de Grille Produit Cartésien et Striding
*   **Priorité** : P0
*   **Dépendances** : T23, T24
*   **Objectif** : Configurer la génération automatique des grilles de paramètres (param_product=True) et implémenter des pas d'incrémentation configurables (striding) pour limiter le coût de la recherche.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Listes de plages de paramètres (ex: RSI de 14 à 24, pas de 2).
*   **Sorties & Formats** : Grille combinatoire NumPy.
*   **Critère de Succès (Validation Réelle)** : Génération correcte de la grille cartésienne combinant tous les paramètres et respect des contraintes de pas (striding).

### Tâche T27 : Cache LRU de Stockage des Matrices d'Indicateurs
*   **Priorité** : P1
*   **Dépendances** : T23
*   **Objectif** : Implémenter un cache de type LRU (Least Recently Used) pour stocker temporairement les matrices d'indicateurs complexes déjà calculées et éviter des temps d'accès redundants.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Identifiant d'indicateur et paramètres comme clé.
*   **Sorties & Formats** : Matrice d'indicateur récupérée depuis la mémoire vive.
*   **Critère de Succès (Validation Réelle)** : Taux de succès (hit-rate) du cache supérieur à 80% lors de l'exécution de simulations identiques successives.

### Tâche T28 : Downcasting Optionnel float64 vers float32
*   **Priorité** : P2
*   **Dépendances** : T24
*   **Objectif** : Configurer une option de downcasting pour forcer les matrices d'indicateurs de sortie en float32 au lieu du float64 standard afin d'économiser 50% d'espace RAM.
*   **Intégration Workflow** : Entité A (Core)
*   **Entrées & Formats** : Paramètre booléen d'activation du downcasting.
*   **Sorties & Formats** : Matrices NumPy converties en float32 (`vbt.settings.array_wrapper['dtype'] = np.float32`).
*   **Critère de Succès (Validation Réelle)** : Baisse mesurée de près de 50% de la consommation de mémoire vive lors de la génération de grandes matrices d'indicateurs, sans dérive numérique significative.

---

# Section 3 : ML-Core & Simulation

## Sous-section 3.1 : Feature Engineering

### Tâche T29 : Normalisation Vectorisée par Z-Score Glissant et Filtrage des Outliers
*   **Priorité** : P0
*   **Dépendances** : T17
*   **Objectif** : Calculer de manière causale et vectorisée le Z-Score glissant d'une série temporelle sur une fenêtre de lookback $w$ donnée, puis appliquer un écrêtage (clipping) des valeurs extrêmes.
*   **Intégration Workflow** : Pipeline ML
*   **Entrées & Formats** : Tableaux NumPy 1D/2D (float64) ; taille de fenêtre $w$ (int).
*   **Sorties & Formats** : Tableau NumPy de features normalisées.
*   **Critère de Succès (Validation Réelle)** : Z-Score calculé selon la formule causale :
    $$Z_t = \frac{x_t - \mu_{t-w:t-1}}{\sigma_{t-w:t-1}}$$
    avec écrêtage rigide à $[-4.0, +4.0] \sigma$ sans aucune valeur `nan` ou `inf` générée.

### Tâche T30 : Alignement Temporel Multi-Timeframe (Lagging)
*   **Priorité** : P0
*   **Dépendances** : T19
*   **Objectif** : Réaliser l'alignement causal de caractéristiques de fréquences supérieures sur la fréquence de base en appliquant un décalage de 1 unité (shift) sur la fréquence supérieure avant la fusion pour éviter le biais d'anticipation.
*   **Intégration Workflow** : Pipeline ML
*   **Entrées & Formats** : Séries de caractéristiques à fréquences mixtes.
*   **Sorties & Formats** : Matrice de caractéristiques fusionnée alignée sur la fréquence de base.
*   **Critère de Succès (Validation Réelle)** : Vérification mathématique qu'aucune information future n'est projetée sur le passé : la valeur d'une bougie supérieure 1H à l'index $t$ (5min) correspond à la bougie clôturée à $t-1$ (1H).

### Tâche T31 : Calcul de la Cible de Volatilité Ajustée
*   **Priorité** : P1
*   **Dépendances** : T29
*   **Objectif** : Implémenter le calcul de la variable cible continue $y_t$ définie comme le rendement logarithmique normalisé par la volatilité glissante locale sur un horizon de prédiction $n$ donné.
*   **Intégration Workflow** : Pipeline ML
*   **Entrées & Formats** : Tableau de prix (Close) ; horizon de prédiction $n$ (int) ; volatilité locale estimée.
*   **Sorties & Formats** : Tenseur cible $y$ (NumPy array 1D).
*   **Critère de Succès (Validation Réelle)** : Calcul exact et stable de la formule :
    $$y_t = \frac{\ln(P_{t+n}) - \ln(P_t)}{\sigma_{vol}}$$
    sans division par zéro en cas de volatilité nulle.

### Tâche T32 : Pipeline d'Assemblage des Tenseurs Train/Test
*   **Priorité** : P0
*   **Dépendances** : T29, T30, T31
*   **Objectif** : Concaténer et aligner les caractéristiques normalisées $X$ et les cibles $y$, puis supprimer les lignes initiales correspondant à la période de mise en route (warmup period).
*   **Intégration Workflow** : Pipeline ML
*   **Entrées & Formats** : Tableaux NumPy de caractéristiques et de cibles.
*   **Sorties & Formats** : Matrice $X$ (n_samples x n_features) et vecteur $y$ (n_samples,).
*   **Critère de Succès (Validation Réelle)** : Tenseurs d'entraînement construits de manière intègre, sans valeurs NaN, prêts pour l'alimentation des modèles de Machine Learning.

---

## Sous-section 3.2 : Simulation Portfolio (Vectorbt Pro)

### Tâche T33 : Calcul Vectorisé du PnL Non-Réalisé (Mark-to-Market)
*   **Priorité** : P0
*   **Dépendances** : T01
*   **Objectif** : Développer le module de calcul vectorisé en continu du PnL non-réalisé pour les positions Long et Short ouvertes, mis à jour à chaque pas de temps.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Prix du marché (float64) ; tailles de position $Q$ (float64) ; prix d'entrée moyen $P_{entry}$ (float64).
*   **Sorties & Formats** : Tableau NumPy de $UPnL_t$ par pas de temps.
*   **Critère de Succès (Validation Réelle)** : Calcul exact de la formule :
    $$UPnL_t = \sum_{i \in Pos} Q_i \times Side_i \times (P_{t,i} - P_{entry,i})$$
    à chaque instant de la simulation.

### Tâche T34 : Moteur de Simulation de Compte Marge Croisée (Crossed Margin)
*   **Priorité** : P0
*   **Dépendances** : T33
*   **Objectif** : Modéliser le comportement d'un compte de trading à marge croisée où les pertes et profits non-réalisés de l'ensemble des positions ouvertes partagent la même base de capital collatéral.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Solde initial du compte $B_t$ ; vecteur des $UPnL_t$.
*   **Sorties & Formats** : Série de valeur de l'équité globale $E_t = B_t + UPnL_t$.
*   **Critère de Succès (Validation Réelle)** : Simulation exacte du capital disponible prenant en compte la compensation bidirectionnelle des gains/pertes des positions Long et Short actives.

### Tâche T35 : Marge de Maintenance et Condition de Ruine (Forced Liquidation)
*   **Priorité** : P0
*   **Dépendances** : T34
*   **Objectif** : Implémenter le calcul vectorisé de la Marge de Maintenance ($MM_t$) requise et générer un signal de sortie forcée (`CloseAll`) si l'équité globale du compte descend sous ce seuil.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Exposition par actif ; prix courants ; taux MMR (Maintenance Margin Rate, ex: 0.5%).
*   **Sorties & Formats** : Vecteur de signaux de liquidation (booléens).
*   **Critère de Succès (Validation Réelle)** : Calcul correct de la marge requis :
    $$MM_t = \sum_{i \in Pos} |Q_i \times P_{t,i}| \times MMR_i$$
    et déclenchement automatique d'un signal `CloseAll` à l'index exact $t$ où $E_t \leq MM_t$.

### Tâche T36 : Modélisation des Coûts de Transaction et du Slippage
*   **Priorité** : P1
*   **Dépendances** : T34
*   **Objectif** : Modéliser un barème réaliste de frais de transaction (Maker/Taker) et appliquer un modèle de slippage (glissement de prix) pour pénaliser les exécutions simulées.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Signaux d'ordres d'achat/vente ; structure de frais et paramètres de slippage.
*   **Sorties & Formats** : Balance du portefeuille nette des coûts de transaction.
*   **Critère de Succès (Validation Réelle)** : Intégration correcte des coûts et du slippage sur chaque trade, vérifiée par la réduction correspondante des performances du portefeuille par rapport au cas idéal.

### Tâche T37 : Calcul du Score Composite (Sortino et Pénalité Drawdown)
*   **Priorité** : P1
*   **Dépendances** : T34
*   **Objectif** : Calculer de manière vectorisée le Ratio de Sortino (basé uniquement sur l'écart-type des rendements négatifs) et lui appliquer un facteur de pénalité quadratique si le Drawdown Maximum (MaxDD) dépasse un seuil toléré.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Série de rendements du portefeuille ; Max Drawdown mesuré ; seuil de tolérance (ex: 20%).
*   **Sorties & Formats** : Valeur du score composite final $J$ (float).
*   **Critère de Succès (Validation Réelle)** : Calcul correct de la métrique composite :
    $$J = Sortino \times (1 - Penalite_{dd})$$
    avec
    $$Penalite_{dd} = \left(\frac{MaxDD}{Seuil_{tol}}\right)^2$$
    où le score s'effondre exponentiellement dès que le Drawdown Maximum dépasse la limite fixée.

---

## Sous-section 3.3 : Walk-Forward Optimization (WFO)

### Tâche T38 : Découpage Walk-Forward Temporel et Purge d'Embargo
*   **Priorité** : P0
*   **Dépendances** : T32
*   **Objectif** : Créer un générateur d'index pour les fenêtres glissantes (Rolling IS/OOS) assurant une chronologie stricte et implémenter un embargo (purge) pour exclure les données à la transition Train/Test pour casser l'autocorrélation.
*   **Intégration Workflow** : Pipeline ML
*   **Entrées & Formats** : Série temporelle ; taille de fenêtre $W_{len}$ ; ratio $R_{train}$ ; taille d'embargo.
*   **Sorties & Formats** : Listes d'indices NumPy pour les segments IS et OOS.
*   **Critère de Succès (Validation Réelle)** : Validation physique qu'aucun échantillon du segment de test n'est présent dans le segment d'entraînement associé, ni aucun échantillon de transition sous embargo.

### Tâche T39 : Pipeline d'Optimisation Optuna et Pruning Callback
*   **Priorité** : P0
*   **Dépendances** : T37, T38
*   **Objectif** : Intégrer l'optimiseur Optuna pour la recherche globale asynchrone des meilleurs hyperparamètres (en maximisant le score composite $J$) et utiliser un callback d'élagage (pruning) pour rejeter les essais non prometteurs.
*   **Intégration Workflow** : Pipeline ML
*   **Entrées & Formats** : Grille d'espace de recherche (JSON) ; fonction objectif Python.
*   **Sorties & Formats** : Paramètres optimaux de la simulation.
*   **Critère de Succès (Validation Réelle)** : Élagage réussi des essais dont les performances intermédiaires sont inférieures à la médiane des essais passés, permettant un gain de temps de calcul mesurable.

### Tâche T40 : Indice de Robustesse (Drift) et Rejet des Anomalies
*   **Priorité** : P1
*   **Dépendances** : T39
*   **Objectif** : Calculer l'indice de robustesse $RI$ pour quantifier la dégradation de performance entre In-Sample et Out-Of-Sample, et rejeter les modèles sujets au surapprentissage ou aux anomalies de chance ("Lucky Strike").
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Métriques Sharpe IS et Sharpe OOS de chaque segment.
*   **Sorties & Formats** : Décision de validation/rejet du segment (booléen).
*   **Critère de Succès (Validation Réelle)** : Validation que le système rejette automatiquement les modèles si $RI < 0.5$ (perte de plus de 50% de performance) ou si $RI > 1.5$ (signe d'anomalie statistique suspecte).

### Tâche T41 : Assemblage des Segments OOS (Stitching)
*   **Priorité** : P0
*   **Dépendances** : T38, T40
*   **Objectif** : Concaténer séquentiellement les courbes d'équité générées sur les fenêtres de test Out-Of-Sample pour former le bilan de performance consolidé final.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Liste des séries d'équité OOS par segment validé.
*   **Sorties & Formats** : Série temporelle d'équité stitched unique.
*   **Critère de Succès (Validation Réelle)** : Production d'un historique de performance global OOS continu et calcul des statistiques globales (Sortino, MaxDD, Sharpe final) sans biais de sélection.

---

# Section 4 : UI & API Gateway

## Sous-section 4.1 : Backend & IPC

### Tâche T42 : Serveur API Gateway FastAPI
*   **Priorité** : P0
*   **Dépendances** : T01
*   **Objectif** : Créer le point d'entrée API avec FastAPI pour piloter les fonctions du Core Engine et exposer les états de l'application.
*   **Intégration Workflow** : UI / Core
*   **Entrées & Formats** : Requêtes REST HTTP (JSON).
*   **Sorties & Formats** : Réponses JSON de statut et de contrôle.
*   **Critère de Succès (Validation Réelle)** : Latence moyenne des appels API REST inférieure à 20 ms hors calculs lourds.

### Tâche T43 : Pont de Communication IPC ZeroMQ / Sockets
*   **Priorité** : P0
*   **Dépendances** : T42
*   **Objectif** : Implémenter un pont de messagerie binaire inter-processus (IPC) rapide utilisant ZeroMQ pour transférer les tenseurs NumPy et données de prix volumineuses du Core Engine vers l'API sans surcharge de sérialisation JSON.
*   **Intégration Workflow** : UI / Core
*   **Entrées & Formats** : Tenseurs NumPy en mémoire.
*   **Sorties & Formats** : Payloads binaires (MessagePack / PyArrow).
*   **Critère de Succès (Validation Réelle)** : Transfert fluide de grands blocs de données vers l'API sans ralentissement ou blocage du thread principal de gestion REST.

### Tâche T44 : Gestionnaire Centralisé de l'État Applicatif
*   **Priorité** : P1
*   **Dépendances** : T42
*   **Objectif** : Développer un module de gestion d'état centralisé côté serveur pour maintenir l'état de session utilisateur, les configurations d'indicateurs et le statut d'avancement des calculs en cours.
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Événements de changement d'état.
*   **Sorties & Formats** : Fichier/Structure JSON d'état global.
*   **Critère de Succès (Validation Réelle)** : Persistance et restauration complète de la configuration et de l'affichage de l'interface en cas de rechargement de page de l'utilisateur.

### Tâche T45 : File d'Attente pour Calculs Asynchrones
*   **Priorité** : P1
*   **Dépendances** : T42, T44
*   **Objectif** : Mettre en œuvre un système de tâches en arrière-plan pour déléguer les exécutions de simulations et optimisations WFO lourdes à un processus worker dédié pour ne pas saturer l'API.
*   **Intégration Workflow** : UI / Core
*   **Entrées & Formats** : Commandes de lancement de backtest / d'optimisation.
*   **Sorties & Formats** : ID de tâche unique ; statut de progression (en attente, actif, terminé).
*   **Critère de Succès (Validation Réelle)** : Interface utilisateur et API REST réactives et fluides pendant le déroulement d'une recherche d'hyperparamètres de plusieurs minutes.

---

## Sous-section 4.2 : Frontend & Visualisation

### Tâche T46 : Page Ingestion : Interface de Contrôle et Progression WebSocket
*   **Priorité** : P1
*   **Dépendances** : T42
*   **Objectif** : Développer l'écran de pilotage de l'ingestion des données historiques et temps réel, intégrant des boutons d'action (Start/Stop) et une barre de progression animée via un flux d'événements WebSocket.
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Événements WebSocket de progression JSON.
*   **Sorties & Formats** : Interface utilisateur React (HTML/CSS).
*   **Critère de Succès (Validation Réelle)** : Visualisation fluide et sans saccade de la progression en direct lors de l'ingestion d'historiques.

### Tâche T47 : Page Charting : Graphique de Bougies Japonaises (OHLCV)
*   **Priorité** : P0
*   **Dépendances** : T43
*   **Objectif** : Créer le composant graphique interactif principal pour tracer les chandeliers OHLCV en exploitant une librairie performante (ex: Lightweight Charts).
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Données de bougies NumPy transmises en format binaire ou JSON optimisé.
*   **Sorties & Formats** : Graphique interactif sur Canvas / WebGL.
*   **Critère de Succès (Validation Réelle)** : Rendu fluide et interactif à 60 fps constants lors d'actions de zoom ou de défilement sur un historique de plus de 10 000 bougies.

### Tâche T48 : Page Charting : Superposition Step-wise Multi-Timeframe
*   **Priorité** : P1
*   **Dépendances** : T47
*   **Objectif** : Rendre possible l'affichage d'indicateurs de fréquences supérieures (ex: SMA 1H) sur le graphique de fréquence inférieure (5min) avec un alignement visuel strict en marches d'escalier (step) pour préserver la causalité.
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Série temporelle d'indicateur de fréquence supérieure.
*   **Sorties & Formats** : Tracé en escalier superposé sur le graphique de prix.
*   **Critère de Succès (Validation Réelle)** : Vérification visuelle et structurelle du tracé : la valeur reste constante sur les bougies de fréquence inférieure de la période courante, ne changeant qu'au début de la période suivante.

### Tâche T49 : Page Config : Formulaire Formulaire Dynamique basé sur JSON Schema
*   **Priorité** : P1
*   **Dépendances** : T22
*   **Objectif** : Concevoir le composant Frontend React capable de générer à la volée des formulaires de saisie de paramètres d'indicateurs basés sur les schémas JSON exportés par l'introspection Core.
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Fichier JSON Schema des signatures d'indicateurs.
*   **Sorties & Formats** : Formulaires d'UI réactifs.
*   **Critère de Succès (Validation Réelle)** : Ajout immédiat d'un indicateur dans l'Algo-Core entraînant la mise à disposition instantanée de son formulaire de réglage dans l'interface sans aucun redéploiement d'UI.

### Tâche T50 : Page Résultats : Heatmaps de l'Espace des Paramètres
*   **Priorité** : P1
*   **Dépendances** : T45
*   **Objectif** : Développer un widget interactif de cartographie 2D/3D (Heatmap) pour visualiser l'espace des paramètres testé durant la phase d'optimisation par Optuna.
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Données des essais Optuna (scores, paramètres).
*   **Sorties & Formats** : Graphique Plotly de Heatmap.
*   **Critère de Succès (Validation Réelle)** : Rendu interactif permettant le survol des zones de performance et l'application de filtres dynamiques de paramètres.

### Tâche T51 : Page Résultats : Comparateur d'Équité OOS vs Buy-and-Hold
*   **Priorité** : P1
*   **Dépendances** : T41
*   **Objectif** : Implémenter le graphique interactif permettant de comparer la courbe d'équité stitched finale des segments OOS avec la performance d'une stratégie passive de type Buy-and-Hold.
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Série temporelle d'équité OOS et historique des cours de l'actif.
*   **Sorties & Formats** : Graphique linéaire comparatif.
*   **Critère de Succès (Validation Réelle)** : Affichage synchronisé des courbes de performance avec calcul et affichage dynamique des indicateurs d'alpha et d'excès de rendement.

### Tâche T52 : Terminal de Visualisation des Logs Système
*   **Priorité** : P2
*   **Dépendances** : T42
*   **Objectif** : Intégrer un panneau de type console dans l'interface utilisateur pour écouter et afficher les flux de logs système du serveur via un WebSocket.
*   **Intégration Workflow** : UI
*   **Entrées & Formats** : Messages de logs formatés en JSON via WebSocket stream.
*   **Sorties & Formats** : Console HTML de logs avec coloration syntaxique par gravité.
*   **Critère de Succès (Validation Réelle)** : Affichage réactif des logs dans l'UI avec une latence inférieure à 100 ms par rapport à l'événement serveur.

---

# Section 5 : Quality, DevOps & Deployment

## Sous-section 5.1 : Tests & Validation

### Tâche T53 : Tests Unitaires : Moteur de Resampling JIT
*   **Priorité** : P0
*   **Dépendances** : T17, T18, T19
*   **Objectif** : Écrire la suite de tests unitaires couvrant l'ensemble des cas limites du resampling JIT en Numba.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Jeux de données de test contenant des volumes nuls, des trous temporels et des séries discontinues.
*   **Sorties & Formats** : Résultats Pytest.
*   **Critère de Succès (Validation Réelle)** : Couverture de test de 100% sur le fichier de resampling JIT ; aucun échec de validation sur les cas limites.

### Tâche T54 : Tests Unitaires : Validation Croisée des Indicateurs (VBT vs TA-Lib C)
*   **Priorité** : P0
*   **Dépendances** : T23, T24
*   **Objectif** : Mettre en œuvre des tests de validation numérique croisée pour s'assurer que les indicateurs générés dynamiquement par Vectorbt fournissent des résultats équivalents à ceux de TA-Lib C.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Séries de cours historiques réelles et configurations d'indicateurs variées.
*   **Sorties & Formats** : Rapport d'écart numérique absolu.
*   **Critère de Succès (Validation Réelle)** : Différence de calcul absolue maximale inférieure à $1\text{e-}9$ sur l'ensemble des indicateurs de la grille de validation.

### Tâche T55 : Tests d'Intégration : Validation de Flux de Bout en Bout
*   **Priorité** : P0
*   **Dépendances** : T09, T14, T32, T41, T53, T54
*   **Objectif** : Concevoir des tests d'intégration simulant le parcours complet des données dans la plateforme (ingestion $\rightarrow$ persistance HDF5 $\rightarrow$ resample $\rightarrow$ features $\rightarrow$ backtest).
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Script de test d'intégration globale.
*   **Sorties & Formats** : Code de retour de test global (0 si succès).
*   **Critère de Succès (Validation Réelle)** : Exécution correcte du pipeline complet sur un jeu de données de test sans crash logiciel.

### Tâche T56 : Benchmarking de Performance CPU/RAM
*   **Priorité** : P1
*   **Dépendances** : T55
*   **Objectif** : Réaliser des profils de performance en ressources système pour s'assurer de l'absence de fuites de mémoire vive et localiser les goulots d'étranglement de calcul sous Numba.
*   **Intégration Workflow** : Évaluation
*   **Entrées & Formats** : Outils de profilage (`cProfile`, `memory_profiler`).
*   **Sorties & Formats** : Rapports de profiling CPU et d'occupation RAM.
*   **Critère de Succès (Validation Réelle)** : Consommation de mémoire RAM stable sous la barre des 8 Go autorisés lors d'un cycle de calcul ininterrompu de 24 heures.

### Tâche T57 : Test de Stress de Résilience Réseau
*   **Priorité** : P1
*   **Dépendances** : T11, T15
*   **Objectif** : Valider la résilience du système face à des pannes planifiées en provoquant des déconnexions réseau forcées et des rejets d'API.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Scénarios de pannes réseau programmés.
*   **Sorties & Formats** : Logs d'erreurs et suivi de reprise.
*   **Critère de Succès (Validation Réelle)** : Reconnexion automatique et récupération totale de l'état système après coupure de 15s sans perte de données ni blocage applicatif.

---

## Sous-section 5.2 : Packaging & Deployment

### Tâche T58 : Dockerfiles Multi-stage (Core et UI)
*   **Priorité** : P1
*   **Dépendances** : T01
*   **Objectif** : Écrire des Dockerfiles de production hautement optimisés, séparant le Core Engine (image Python enrichie des bibliothèques de calcul scientifique et support GPU) et le Layer UI (compilation et service des assets statiques React).
*   **Intégration Workflow** : Ingestion / UI
*   **Entrées & Formats** : Code source applicatif.
*   **Sorties & Formats** : Images Docker compilées.
*   **Critère de Succès (Validation Réelle)** : Compilation réussie des deux conteneurs et réduction significative de la taille des images finales de production.

### Tâche T59 : Orchestrateur de Services Docker Compose
*   **Priorité** : P1
*   **Dépendances** : T58
*   **Objectif** : Configurer le fichier d'orchestration multi-conteneurs `docker-compose.yml` pour lier le Core, l'API Gateway, le Frontend, ainsi que la configuration des volumes persistants de données et des réseaux internes.
*   **Intégration Workflow** : Ingestion / UI
*   **Entrées & Formats** : Fichier `docker-compose.yml`.
*   **Sorties & Formats** : Environnement applicatif conteneurisé.
*   **Critère de Succès (Validation Réelle)** : Initialisation et démarrage complet de l'ensemble des services de la plateforme via une commande unique `docker-compose up -d`.

### Tâche T60 : Script Bash d'Initialisation et d'Entrypoint
*   **Priorité** : P1
*   **Dépendances** : T59
*   **Objectif** : Écrire un script shell exécuté au démarrage des conteneurs pour s'assurer de la présence des dossiers de données, réaliser les vérifications initiales de structure et lancer l'application de manière sécurisée.
*   **Intégration Workflow** : Ingestion
*   **Entrées & Formats** : Script shell `entrypoint.sh`.
*   **Sorties & Formats** : logs de démarrage et statut du système.
*   **Critère de Succès (Validation Réelle)** : Démarrage propre du conteneur, création automatique des arborescences de données absentes et initialisation correcte des fichiers de base de données.

---

## 2. Plan de Validation DevOps

Le plan de test s'articule autour de trois axes de validation :

### Tests Automatisés
Les tests unitaires et d'intégration seront exécutés en local et dans la CI via la commande :
```bash
pytest tests/ --cov=tradingvbt --cov-fail-under=80 -v
```

### Benchmarks de Performance
Mesure des temps d'exécution critiques pour valider les contraintes de latence basse fréquence :
```python
python benchmarks/run_benchmarks.py
```
*   *Validation Resampling* : 1 000 000 de lignes agrégées en moins de 50 ms.
*   *Validation Cache* : Hit-rate du LRU cache $> 80\%$ lors de requêtes successives.

### Tests de Robustesse Algorithmique (IS vs OOS)
Calcul de l'indice de robustesse pour chaque modèle optimisé :
$$RI = \frac{Sharpe_{OOS}}{Sharpe_{IS}}$$
*   **Rejet automatique** si $RI < 0.5$ ou $RI > 1.5$.
*   **Rejet automatique** en cas d'inversion ($PnL_{OOS} < 0$ et $PnL_{IS} > 0$).
