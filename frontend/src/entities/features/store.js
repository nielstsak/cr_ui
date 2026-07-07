// frontend/src/entities/features/store.js
import { create } from 'zustand';
import { featuresApi } from './api.js';

export const useFeatureStore = create((set, get) => ({
  selectedIndicatorTypes: [],
  deepenedColumns: {},
  activeTaskId: null,
  isCalculating: false,
  error: null,

  setSelectedIndicatorTypes: (types) => {
    set({ selectedIndicatorTypes: types });
  },

  toggleIndicatorType: (type) => {
    set((state) => {
      const idx = state.selectedIndicatorTypes.indexOf(type);
      if (idx > -1) {
        return {
          selectedIndicatorTypes: state.selectedIndicatorTypes.filter((t) => t !== type)
        };
      } else {
        return {
          selectedIndicatorTypes: [...state.selectedIndicatorTypes, type]
        };
      }
    });
  },

  fetchDeepenedColumns: async (symbol) => {
    if (!symbol) return;
    try {
      const data = await featuresApi.getDeepenedColumns(symbol);
      set({ deepenedColumns: data });
    } catch (err) {
      console.error("Erreur de récupération des colonnes approfondies:", err);
      set({ deepenedColumns: {} });
    }
  },

  startFeatureDeepening: async (symbol) => {
    const types = get().selectedIndicatorTypes;
    if (!symbol || types.length === 0) return;

    set({ isCalculating: true, error: null, activeTaskId: null });
    try {
      const res = await featuresApi.deepen(symbol, types);
      set({ activeTaskId: res.task_id });
    } catch (err) {
      set({ isCalculating: false, error: err.message });
    }
  },

  setTaskId: (taskId) => {
    set({ activeTaskId: taskId });
  },

  setCalculating: (calculating) => {
    set({ isCalculating: calculating });
  },

  setError: (err) => {
    set({ error: err });
  }
}));
