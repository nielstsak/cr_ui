
import { client } from '../../shared/api/client.js';

export const chartingApi = {
  getOhlcv: (params) => {
    return client.post('/api/data/ohlcv', {
      exchange: params.exchange || 'BINANCE',
      symbol: params.symbol,
      timeframe: params.timeframe,
      start_time: params.start_time,
      end_time: params.end_time,
      features: params.features
    });
  }
};