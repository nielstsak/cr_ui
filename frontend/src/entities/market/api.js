
import { client } from '../../shared/api/client.js';

export const marketApi = {
  getSymbols: () => {
    return client.get('/api/runs/symbols');
  },

  getLocalPairs: () => {
    return client.get('/api/ingestion/status');
  },

  getStats: (symbol) => {
    return client.get(`/api/ingestion/stats/${symbol}`);
  },

  getVbtInfo: (symbol) => {
    return client.get(`/api/ingestion/vbt-info/${symbol}`);
  },

  executeVbtFetch: (params) => {
    return client.post('/api/ingestion/vbt-fetch', {
      symbol: params.symbol.toUpperCase().replace('/', ''),
      client: params.client || null,
      start: params.start || null,
      end: params.end || null,
      timeframe: params.timeframe || null,
      limit: params.limit ? parseInt(params.limit, 10) : null,
      delay: params.delay ? parseFloat(params.delay) : null,
      show_progress: !!params.show_progress
    });
  },

  deleteSymbol: (symbol) => {
    return client.delete(`/api/ingestion/delete/${symbol}`);
  },

  addTimeframe: (symbol, targetTf) => {
    return client.post('/api/ingestion/add-timeframe', {
      symbol,
      target_timeframe: targetTf
    });
  }
};