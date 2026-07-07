import { create } from 'zustand';

export const useChartingStore = create((set) => ({
  multiTfData: {},
  isLoading: false,

  setMultiTfData: (data) => set({ multiTfData: data }),
  setIsLoading: (val) => set({ isLoading: val })
}));