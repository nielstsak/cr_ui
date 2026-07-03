// FICHIER : frontend/src/store/useAppStore.js
import { create } from 'zustand';

/**
 * Store global de gestion de l'état (Zustand) pour l'interface de pilotage.
 * Orchestre les communications synchrones/asynchrones avec la Gateway API.
 */
const useAppStore = create((set, get) => ({
  symbols: [],
  activeSymbol: 'BTCUSDT',
  sessions: [],
  activeSession: null,
  localPairs: [],
  descStats: null, // Données statistiques descriptives MTF pour la table d'informations (T47)

  isLoading: false,
  error: null,

  selectedOverlays: ['SMA'],
  selectedOscillators: ['RSI'],
  indicatorParams: {
    SMA: { timeperiod: 20 },
    RSI: { timeperiod: 14 }
  },

  setActiveSymbol: (symbol) => {
    set({ activeSymbol: symbol });
    get().fetchSessions(symbol);
    get().fetchStats(symbol);
  },

  setActiveSession: (session) => set({ activeSession: session }),

  setSelectedOverlays: (overlays) => set({ selectedOverlays: overlays }),

  setSelectedOscillators: (oscillators) => set({ selectedOscillators: oscillators }),

  setIndicatorParam: (indicator, paramName, value) => set((state) => ({
    indicatorParams: {
      ...state.indicatorParams,
      [indicator]: {
        ...(state.indicatorParams[indicator] || {}),
        [paramName]: value
      }
    }
  })),

  /**
   * Récupère la liste globale des symboles indexés dans le moteur runs.db
   */
  fetchSymbols: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch('http://localhost:8000/api/runs/symbols');
      if (!response.ok) throw new Error('Échec de la récupération des symboles.');
      const symbols = await response.json();
      set({ symbols, isLoading: false });
      
      if (symbols.length > 0) {
        const currentSymbol = get().activeSymbol;
        const targetSymbol = symbols.includes(currentSymbol) ? currentSymbol : symbols[0];
        get().setActiveSymbol(targetSymbol);
      }
    } catch (error) {
      set({ error: error.message, isLoading: false });
    }
  },

  /**
   * Récupère les sessions actives du symbole courant
   */
  fetchSessions: async (symbol) => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch(`http://localhost:8000/api/runs/sessions/${symbol}`);
      if (!response.ok) throw new Error('Échec de la récupération des sessions.');
      const sessions = await response.json();
      set({ sessions, isLoading: false });
      
      if (sessions.length > 0) {
        get().setActiveSession(sessions[0]);
      } else {
        get().setActiveSession(null);
      }
    } catch (error) {
      set({ error: error.message, isLoading: false });
    }
  },

  /**
   * Récupère la liste des paires stockées localement et leurs unités de temps associées (T46)
   */
  fetchLocalPairs: async () => {
    try {
      const response = await fetch('http://localhost:8000/api/ingestion/status');
      if (!response.ok) throw new Error('Impossible de charger le statut des paires.');
      const data = await response.json();
      set({ localPairs: data.active_pairs });
    } catch (err) {
      console.error("Erreur de synchronisation locale de paires :", err);
    }
  },

  /**
   * Récupère les données descriptives analytiques MTF pour le tableau d'informations (T47)
   */
  fetchStats: async (symbol) => {
    if (!symbol) return;
    try {
      const response = await fetch(`http://localhost:8000/api/ingestion/stats/${symbol}`);
      if (!response.ok) {
        set({ descStats: null });
        return;
      }
      const stats = await response.json();
      set({ descStats: stats });
    } catch (err) {
      console.error(`Erreur d'analyse descriptive pour ${symbol} :`, err);
      set({ descStats: null });
    }
  },

  /**
   * Action de purge d'un symbole sur disque et en base SQL (T46)
   */
  deleteSymbol: async (symbol) => {
    try {
      const response = await fetch(`http://localhost:8000/api/ingestion/delete/${symbol}`, {
        method: "DELETE"
      });
      if (response.ok) {
        get().fetchLocalPairs();
        set({ descStats: null });
        get().fetchSymbols();
      } else {
        const data = await response.json();
        throw new Error(data.detail || "La suppression a échoué.");
      }
    } catch (err) {
      set({ error: err.message });
    }
  },

  /**
   * Action d'actualisation locale MTF (T46)
   */
  refreshSymbol: async (symbol) => {
    try {
      const response = await fetch(`http://localhost:8000/api/ingestion/refresh/${symbol}`, {
        method: "POST"
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Échec de l'actualisation.");
      get().fetchLocalPairs();
      return data.task_id;
    } catch (err) {
      set({ error: err.message });
      return null;
    }
  },

  /**
   * Action de génération d'une unité de temps manquante par rééchantillonnage de précision
   */
  addTimeframe: async (symbol, targetTf) => {
    try {
      const response = await fetch('http://localhost:8000/api/ingestion/add-timeframe', {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, target_timeframe: targetTf })
      });
      if (response.ok) {
        get().fetchLocalPairs();
        get().fetchStats(symbol);
      } else {
        const data = await response.json();
        throw new Error(data.detail || "Échec de l'ajout d'unité de temps.");
      }
    } catch (err) {
      set({ error: err.message });
    }
  }
}));

export default useAppStore;