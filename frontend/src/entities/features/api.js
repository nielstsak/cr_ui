// frontend/src/entities/features/api.js
import { client } from '../../shared/api/client.js';

export const featuresApi = {
  deepen: (symbol, indicatorTypes) => {
    return client.post('/api/features/deepen', {
      symbol: symbol.toUpperCase(),
      indicator_types: indicatorTypes
    });
  },

  getDeepenedColumns: (symbol) => {
    return client.get(`/api/features/deepened-columns/${symbol.toUpperCase()}`);
  }
};
