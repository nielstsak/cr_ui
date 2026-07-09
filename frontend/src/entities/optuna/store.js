// frontend/src/entities/optuna/store.js
import { create } from 'zustand';
import { optunaApi } from './api.js';

export const useOptunaStore = create((set, get) => ({
  studies: [],
  activeTaskId: null,
  isOptimizing: false,
  optimizationProgress: 0,
  optimizationStatus: null,
  optimizationError: null,
  
  selectedStudy: null,
  selectedTrial: null,
  isLoadingDetails: false,
  detailsError: null,
  featureSymbols: [],

  fetchStudies: async () => {
    try {
      const data = await optunaApi.getStudies();
      set({ studies: data });
    } catch (err) {
      console.error("Erreur lors de la récupération des études:", err);
      set({ studies: [] });
    }
  },

  startOptimization: async (config) => {
    set({ 
      isOptimizing: true, 
      optimizationProgress: 0, 
      optimizationStatus: 'starting', 
      optimizationError: null, 
      activeTaskId: null 
    });
    try {
      const res = await optunaApi.optimize(config);
      set({ activeTaskId: res.task_id });
    } catch (err) {
      set({ 
        isOptimizing: false, 
        optimizationStatus: 'failed', 
        optimizationError: err.message 
      });
    }
  },

  fetchStudyDetails: async (studyId) => {
    if (!studyId) return;
    set({ isLoadingDetails: true, detailsError: null, selectedStudy: null, selectedTrial: null });
    try {
      const data = await optunaApi.getStudyDetails(studyId);
      set({ selectedStudy: data, isLoadingDetails: false });
      
      // Default select the first trial on the Pareto front if available, or first complete trial
      if (data.trials && data.trials.length > 0) {
        let defaultTrial = null;
        if (data.pareto_front && data.pareto_front.length > 0) {
          defaultTrial = data.trials.find(t => t.trial_number === data.pareto_front[0]);
        }
        if (!defaultTrial) {
          defaultTrial = data.trials.find(t => t.state === "COMPLETE");
        }
        if (defaultTrial) {
          set({ selectedTrial: defaultTrial });
        }
      }
    } catch (err) {
      set({ detailsError: err.message, isLoadingDetails: false });
    }
  },

  deleteStudy: async (studyId) => {
    try {
      await optunaApi.deleteStudy(studyId);
      await get().fetchStudies();
      if (get().selectedStudy?.study_id === studyId) {
        set({ selectedStudy: null, selectedTrial: null });
      }
    } catch (err) {
      console.error("Erreur de suppression de l'étude:", err);
    }
  },

  fetchFeatureSymbols: async () => {
    try {
      const data = await optunaApi.getFeatureSymbols();
      set({ featureSymbols: data });
    } catch (err) {
      console.error("Erreur de récupération des symboles de features:", err);
      set({ featureSymbols: [] });
    }
  },

  deleteFeatureSymbol: async (symbol) => {
    try {
      await optunaApi.deleteFeatureSymbol(symbol);
      await get().fetchFeatureSymbols();
    } catch (err) {
      console.error("Erreur de suppression du dossier de features:", err);
    }
  },

  selectTrial: (trial) => {
    set({ selectedTrial: trial });
  },

  setTaskId: (taskId) => {
    set({ activeTaskId: taskId });
  },

  setOptimizing: (optimizing) => {
    set({ isOptimizing: optimizing });
  },

  setOptimizationProgress: (progress) => {
    set({ optimizationProgress: progress });
  },

  setOptimizationStatus: (status) => {
    set({ optimizationStatus: status });
  },

  setOptimizationError: (err) => {
    set({ optimizationError: err });
  }
}));
