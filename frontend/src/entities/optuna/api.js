// frontend/src/entities/optuna/api.js
import { client } from '../../shared/api/client.js';

export const optunaApi = {
  optimize: (config) => {
    return client.post('/api/optuna/optimize', config);
  },

  getStudies: () => {
    return client.get('/api/optuna/studies');
  },

  getStudyDetails: (studyId) => {
    return client.get(`/api/optuna/studies/${studyId}/details`);
  },

  deleteStudy: (studyId) => {
    return client.delete(`/api/optuna/studies/${studyId}`);
  },

  getFeatureSymbols: () => {
    return client.get('/api/optuna/features/symbols');
  },

  deleteFeatureSymbol: (symbol) => {
    return client.delete(`/api/optuna/features/symbols/${symbol}`);
  }
};
