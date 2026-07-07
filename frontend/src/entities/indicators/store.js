
// frontend/src/entities/indicators/store.js
import { create } from 'zustand';
import { indicatorsApi } from './api.js';

const pendingMetadata = new Set();

export const useIndicatorStore = create((set, get) => ({
  calculatedIndicators: {}, 
  indicatorMetadata: {},
  indicatorGroups: {}, 
  displayedIndicators: {},

  setCalculatedIndicators: (symbol, indicators) => {
    set((state) => ({
      calculatedIndicators: { ...state.calculatedIndicators, [symbol]: indicators }
    }));
  },

  fetchIndicatorGroups: async () => {
    try {
      const groups = await indicatorsApi.getGroups();
      set({ indicatorGroups: groups });
    } catch (e) {
      console.error(e);
    }
  },

  fetchIndicatorMetadataBulk: async (names) => {
    const currentMeta = get().indicatorMetadata;
    const toFetch = names.filter(name => !currentMeta[name] && !pendingMetadata.has(name));
    if (toFetch.length === 0) return;

    toFetch.forEach(name => pendingMetadata.add(name));

    try {
      const bulkData = await indicatorsApi.getBulkMetadata(toFetch);
      set((state) => ({
        indicatorMetadata: {
          ...state.indicatorMetadata,
          ...bulkData
        }
      }));
    } catch (e) {
      console.error(e);
    } finally {
      toFetch.forEach(name => pendingMetadata.delete(name));
    }
  },

  fetchIndicatorMetadata: async (indName) => {
    const metaCache = get().indicatorMetadata;
    if (metaCache[indName]) return metaCache[indName];

    if (pendingMetadata.has(indName)) return null;
    pendingMetadata.add(indName);

    try {
      const data = await indicatorsApi.getMetadata(indName);
      if (data) {
        set((state) => ({
          indicatorMetadata: { ...state.indicatorMetadata, [indName]: data }
        }));
        return data;
      }
    } catch (e) {
      console.error(e);
    } finally {
      pendingMetadata.delete(indName);
    }
    return null;
  },

  toggleIndicatorOutput: (symbol, indName, tf, outCol, defaultConfig) => {
    set((state) => {
      const symData = state.displayedIndicators[symbol] || {};
      const indData = symData[indName] || {};
      const tfData = indData[tf] || {};

      if (tfData[outCol]) {
        const newTfData = { ...tfData };
        delete newTfData[outCol];
        return {
          displayedIndicators: {
            ...state.displayedIndicators,
            [symbol]: { ...symData, [indName]: { ...indData, [tf]: newTfData } }
          }
        };
      }
      return {
        displayedIndicators: {
          ...state.displayedIndicators,
          [symbol]: { ...symData, [indName]: { ...indData, [tf]: { ...tfData, [outCol]: defaultConfig } } }
        }
      };
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
  }
}));