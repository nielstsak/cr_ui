
// frontend/src/entities/indicators/api.js
import { client } from '../../shared/api/client.js';

export const indicatorsApi = {
  getGroups: () => {
    return client.get('/api/indicators/groups');
  },

  getMetadata: (funcName) => {
    return client.get(`/api/indicator/metadata/${funcName}`);
  },

  getBulkMetadata: (names) => {
    return client.post('/api/indicators/metadata/bulk', { names });
  },

  applyIndicators: (symbol) => {
    return client.post('/api/indicators/apply', { symbol });
  }
};