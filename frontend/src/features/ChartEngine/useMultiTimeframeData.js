
// frontend/src/features/ChartEngine/useMultiTimeframeData.js
import { useEffect } from 'react';
import { useMarketStore } from '../../entities/market/store';
import { useIndicatorStore } from '../../entities/indicators/store';
import { useChartingStore } from '../../entities/charting/store';

export const useMultiTimeframeData = (selectedTf) => {
  const activeSymbol = useMarketStore((state) => state.activeSymbol);
  const descStats = useMarketStore((state) => state.descStats);
  const displayedIndicators = useIndicatorStore((state) => state.displayedIndicators);
  const indicatorGroups = useIndicatorStore((state) => state.indicatorGroups);
  const setMultiTfData = useChartingStore((state) => state.setMultiTfData);
  const setIsLoading = useChartingStore((state) => state.setIsLoading);

  const dispStr = JSON.stringify(displayedIndicators[activeSymbol] || {});
  const groupsStr = JSON.stringify(indicatorGroups);

  useEffect(() => {
    let active = true;

    const fetchAllTimeframes = async () => {
      if (!activeSymbol || !descStats) return;

      const symDisplayed = displayedIndicators[activeSymbol] || {};
      const hasIndicatorsToFetch = Object.keys(symDisplayed).some((indName) => {
        const indTfData = symDisplayed[indName] || {};
        return Object.keys(indTfData).length > 0;
      });

      if (hasIndicatorsToFetch && Object.keys(indicatorGroups).length === 0) return;

      if (!active) return;
      setIsLoading(true);
      try {
        const activeTfs = new Set();
        if (selectedTf) {
          activeTfs.add(selectedTf);
        }

        Object.values(symDisplayed).forEach((indTfData) => {
          Object.keys(indTfData).forEach((tf) => {
            activeTfs.add(tf);
          });
        });

        const tfsToFetch = Array.from(activeTfs).filter(Boolean);
        const results = {};

        await Promise.all(
          tfsToFetch.map(async (tf) => {
            const stats = descStats[tf];
            if (!stats || !stats.start_date || !stats.end_date) return;

            const startStr = stats.start_date.replace(' ', 'T') + ':00Z';
            const endStr = stats.end_date.replace(' ', 'T') + ':00Z';
            const start_time = new Date(startStr).getTime();
            const end_time = new Date(endStr).getTime() + 86400000;

            if (isNaN(start_time) || isNaN(end_time) || start_time <= 0 || end_time <= 0) return;

            const payloadFeatures = {
              OHLCV: ['open', 'high', 'low', 'close', 'volume']
            };

            Object.entries(symDisplayed).forEach(([indName, indTfData]) => {
              if (indTfData[tf]) {
                let groupName = 'UNCATEGORIZED';
                for (const [gName, indicators] of Object.entries(indicatorGroups)) {
                  if (indicators.includes(indName)) {
                    groupName = gName.toUpperCase().replace(/\s+/g, '_');
                    break;
                  }
                }
                const groupKey = `FEATURES/${groupName}`;
                if (!payloadFeatures[groupKey]) {
                  payloadFeatures[groupKey] = [];
                }
                Object.keys(indTfData[tf]).forEach((outCol) => {
                  payloadFeatures[groupKey].push(outCol);
                });
              }
            });

            if (!active) return;
            const res = await fetch('http://localhost:8000/api/data/ohlcv', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                exchange: 'BINANCE',
                symbol: activeSymbol,
                timeframe: tf,
                start_time,
                end_time,
                features: payloadFeatures
              })
            });

            if (res.ok) {
              const data = await res.json();
              if (active) {
                results[tf] = data;
              }
            }
          })
        );

        if (active) {
          setMultiTfData(results);
        }
      } catch (e) {
        console.error(e);
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    };

    fetchAllTimeframes();

    return () => {
      active = false;
    };
  }, [activeSymbol, selectedTf, descStats, dispStr, groupsStr, setMultiTfData, setIsLoading]);
};