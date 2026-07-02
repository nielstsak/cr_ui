import { create } from 'zustand';

const useAppStore = create((set, get) => ({
  symbols: [],
  activeSymbol: 'BTCUSDT',
  sessions: [],
  activeSession: null,

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

  fetchSymbols: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch('http://localhost:8000/api/runs/symbols');
      if (!response.ok) throw new Error('Échec de la récupération des symboles');
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

  fetchSessions: async (symbol) => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch(`http://localhost:8000/api/runs/sessions/${symbol}`);
      if (!response.ok) throw new Error('Échec de la récupération des sessions');
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
  }
}));

export default useAppStore;