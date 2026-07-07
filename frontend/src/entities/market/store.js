
import { create } from 'zustand';
import { marketApi } from './api.js';
import { useIndicatorStore } from '../indicators/store';

export const useMarketStore = create((set, get) => ({
  symbols: [],
  activeSymbol: 'BTCUSDT',
  localPairs: [],
  descStats: null,
  vbtInfo: null,
  isLoading: false,

  setActiveSymbol: (symbol) => {
    set({ activeSymbol: symbol });
    if (symbol) {
      get().fetchStats(symbol);
      get().fetchVbtInfo(symbol);
    }
  },

  fetchLocalPairs: async () => {
    try {
      const data = await marketApi.getLocalPairs();
      set({ localPairs: data.active_pairs });
    } catch (err) {
      console.error(err);
    }
  },

  fetchStats: async (symbol) => {
    if (!symbol) return;
    try {
      const data = await marketApi.getStats(symbol);
      set({ descStats: data });
    } catch (err) {
      set({ descStats: null });
    }
  },

  fetchVbtInfo: async (symbol) => {
    if (!symbol) return;
    try {
      const data = await marketApi.getVbtInfo(symbol);
      set({ vbtInfo: data });
      if (data && data.indicators) {
        useIndicatorStore.getState().setCalculatedIndicators(symbol, data.indicators);
      }
    } catch (err) {
      set({ vbtInfo: null });
    }
  }
}));