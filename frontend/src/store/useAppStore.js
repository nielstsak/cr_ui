// FICHIER : frontend/src/store/useAppStore.js
import { create } from 'zustand';

const useAppStore = create((set, get) => ({
  symbols: [],
  activeSymbol: 'BTCUSDT',
  sessions: [],
  activeSession: null,
  localPairs: [],
  descStats: null,
  vbtInfo: null,

  isLoading: false,
  error: null,

  // Liste des indicateurs détectés sur le disque
  calculatedIndicators: {}, 
  
  // Métadonnées d'outputs
  indicatorMetadata: {},
  
  // Catégorisation TA-Lib (Overlap, Momentum...)
  indicatorGroups: {}, 

  // Configuration visuelle
  displayedIndicators: {},

  setActiveSymbol: (symbol) => {
    set({ activeSymbol: symbol });
    get().fetchSessions(symbol);
    get().fetchStats(symbol);
    get().fetchVbtInfo(symbol);
  },

  setActiveSession: (session) => set({ activeSession: session }),

  // --- ACTIONS INDICATEURS AUTOMATISÉS ---
  
  fetchIndicatorGroups: async () => {
    try {
      const res = await fetch('http://localhost:8000/api/indicators/groups');
      if (res.ok) {
        const groups = await res.json();
        set({ indicatorGroups: groups });
      }
    } catch (e) { console.error("Erreur récupération groupes:", e); }
  },

  fetchIndicatorMetadata: async (indName) => {
    const metaCache = get().indicatorMetadata;
    if (metaCache[indName]) return metaCache[indName];
    
    try {
      const res = await fetch(`http://localhost:8000/api/indicator/metadata/${indName}`);
      if (res.ok) {
        const data = await res.json();
        set(state => ({ indicatorMetadata: { ...state.indicatorMetadata, [indName]: data } }));
        return data;
      }
    } catch (e) {
      console.error("Erreur meta:", e);
    }
    return null;
  },

  applyIndicators: async (symbol) => {
    set({ isLoading: true });
    try {
      const response = await fetch('http://localhost:8000/api/indicators/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol })
      });
      
      if (!response.ok) throw new Error("Échec de la réapplication du Feature Engineering.");
      await get().fetchVbtInfo(symbol);
      
    } catch (error) {
      set({ error: error.message });
    } finally {
      set({ isLoading: false });
    }
  },

  toggleIndicatorOutput: (symbol, indName, tf, outCol, defaultConfig) => {
    set((state) => {
      const symData = state.displayedIndicators[symbol] || {};
      const indData = symData[indName] || {};
      const tfData = indData[tf] || {};

      if (tfData[outCol]) {
        // Suppression
        const newTfData = { ...tfData };
        delete newTfData[outCol];
        return { 
          displayedIndicators: { 
            ...state.displayedIndicators, 
            [symbol]: { ...symData, [indName]: { ...indData, [tf]: newTfData } } 
          } 
        };
      } else {
        // Ajout
        return { 
          displayedIndicators: { 
            ...state.displayedIndicators, 
            [symbol]: { ...symData, [indName]: { ...indData, [tf]: { ...tfData, [outCol]: defaultConfig } } } 
          } 
        };
      }
    });
  },

  updateIndicatorOutputConfig: (symbol, indName, tf, outCol, key, value) => {
    set((state) => {
      const symData = state.displayedIndicators[symbol] || {};
      const indData = symData[indName] || {};
      const tfData = indData[tf] || {};
      const config = tfData[outCol];
      
      if (!config) return state;

      return {
        displayedIndicators: {
          ...state.displayedIndicators,
          [symbol]: {
            ...symData,
            [indName]: {
              ...indData,
              [tf]: {
                ...tfData,
                [outCol]: { ...config, [key]: value }
              }
            }
          }
        }
      };
    });
  },

  // --- ACTIONS SYSTEME ---
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
    } catch (error) { set({ error: error.message, isLoading: false }); }
  },

  fetchSessions: async (symbol) => {
    try {
      const response = await fetch(`http://localhost:8000/api/runs/sessions/${symbol}`);
      const sessions = await response.json();
      set({ sessions });
      if (sessions.length > 0) get().setActiveSession(sessions[0]);
    } catch (error) {}
  },

  fetchLocalPairs: async () => {
    try {
      const response = await fetch('http://localhost:8000/api/ingestion/status');
      const data = await response.json();
      set({ localPairs: data.active_pairs });
    } catch (err) {}
  },

  fetchStats: async (symbol) => {
    if (!symbol) return;
    try {
      const response = await fetch(`http://localhost:8000/api/ingestion/stats/${symbol}`);
      if (!response.ok) return set({ descStats: null });
      const stats = await response.json();
      set({ descStats: stats });
    } catch (err) { set({ descStats: null }); }
  },

  fetchVbtInfo: async (symbol) => {
    if (!symbol) return;
    try {
      const response = await fetch(`http://localhost:8000/api/ingestion/vbt-info/${symbol}`);
      if (!response.ok) return set({ vbtInfo: null });
      const data = await response.json();
      set({ vbtInfo: data });
      
      if (data.indicators) {
        set((state) => ({
          calculatedIndicators: { ...state.calculatedIndicators, [symbol]: data.indicators }
        }));
      }
    } catch (err) { set({ vbtInfo: null }); }
  },

  executeVbtFetch: async (fetchParams) => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch('http://localhost:8000/api/ingestion/vbt-fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: fetchParams.symbol.toUpperCase().replace('/', ''),
          client: fetchParams.client || null,
          start: fetchParams.start || null,
          end: fetchParams.end || null,
          timeframe: fetchParams.timeframe || null,
          limit: fetchParams.limit ? parseInt(fetchParams.limit, 10) : null,
          delay: fetchParams.delay ? parseFloat(fetchParams.delay) : null,
          show_progress: !!fetchParams.show_progress
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "L'acquisition a échoué.");
      return data.task_id;
    } catch (error) {
      set({ error: error.message, isLoading: false });
      return null;
    }
  },

  deleteSymbol: async (symbol) => {
    try {
      const response = await fetch(`http://localhost:8000/api/ingestion/delete/${symbol}`, { method: "DELETE" });
      if (response.ok) {
        get().fetchLocalPairs();
        set((state) => {
          const newCalc = { ...state.calculatedIndicators };
          const newDisp = { ...state.displayedIndicators };
          delete newCalc[symbol];
          delete newDisp[symbol];
          return { descStats: null, vbtInfo: null, calculatedIndicators: newCalc, displayedIndicators: newDisp };
        });
        get().fetchSymbols();
      }
    } catch (err) {}
  },

  refreshSymbol: async (symbol) => {
    try {
      const response = await fetch(`http://localhost:8000/api/ingestion/refresh/${symbol}`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail);
      get().fetchLocalPairs();
      return data.task_id;
    } catch (err) { return null; }
  },

  addTimeframe: async (symbol, targetTf) => {
    try {
      const response = await fetch('http://localhost:8000/api/ingestion/add-timeframe', {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, target_timeframe: targetTf })
      });
      if (response.ok) {
        await get().fetchLocalPairs();
        await get().fetchStats(symbol);
        await get().fetchVbtInfo(symbol);
      } else {
        const data = await response.json();
        throw new Error(data.detail);
      }
    } catch (err) {
      set({ error: err.message });
    }
  }
}));

export default useAppStore;