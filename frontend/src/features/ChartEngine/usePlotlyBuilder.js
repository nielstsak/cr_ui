
// frontend/src/features/ChartEngine/usePlotlyBuilder.js
import { useMemo } from 'react';
import { useMarketStore } from '../../entities/market/store';
import { useIndicatorStore } from '../../entities/indicators/store';
import { useChartingStore } from '../../entities/charting/store';

const safeToISOString = (t) => {
  if (!t) return null;
  try {
    const d = new Date(t);
    return isNaN(d.getTime()) ? null : d.toISOString();
  } catch (e) {
    return null;
  }
};

export const usePlotlyBuilder = (selectedTf) => {
  const activeSymbol = useMarketStore((state) => state.activeSymbol);
  const displayedIndicators = useIndicatorStore((state) => state.displayedIndicators);
  const multiTfData = useChartingStore((state) => state.multiTfData);

  return useMemo(() => {
    const mainData = multiTfData[selectedTf];
    if (!mainData || !mainData.open_time) {
      return { traces: [], layout: {} };
    }

    const traces = [];
    const mainTimeArray = mainData.open_time.map(safeToISOString);

    traces.push({
      x: mainTimeArray,
      open: mainData.open,
      high: mainData.high,
      low: mainData.low,
      close: mainData.close,
      type: 'candlestick',
      name: `${activeSymbol} ${selectedTf}`,
      yaxis: 'y',
      increasing: { line: { color: '#2ecc71', width: 1.5 }, fillcolor: '#2ecc71' },
      decreasing: { line: { color: '#e74c3c', width: 1.5 }, fillcolor: '#e74c3c' }
    });

    const subchartInds = new Set();
    const symDisplayed = displayedIndicators[activeSymbol] || {};

    Object.entries(symDisplayed).forEach(([indName, indTfData]) => {
      Object.entries(indTfData).forEach(([tf, tfData]) => {
        Object.entries(tfData).forEach(([outCol, config]) => {
          const df = multiTfData[tf];
          if (!df || !df[outCol] || !df.open_time) return;

          const xTimes = df.open_time.map(safeToISOString);
          const yData = df[outCol];

          if (config.position === 'overlay') {
            traces.push({
              x: xTimes,
              y: yData,
              type: config.type === 'bar' ? 'bar' : 'scatter',
              mode: config.type === 'bar' ? undefined : config.type,
              name: `${outCol} (${tf})`,
              yaxis: 'y',
              line: config.type === 'lines' ? { color: config.color, width: config.width } : undefined,
              marker: config.type !== 'lines' ? { color: config.color, size: config.type === 'markers' ? config.width * 2 : undefined } : undefined,
              opacity: config.opacity
            });
          } else {
            subchartInds.add(`${indName}_${tf}`);
          }
        });
      });
    });

    const subchartsList = Array.from(subchartInds);
    const baseHeight = 500;
    const subchartHeight = 150;
    const totalHeight = baseHeight + subchartsList.length * subchartHeight;

    const layoutYAxes = {};
    const yDomainPadding = 0.02;
    let currentBottom = 0;

    subchartsList.forEach((indTfKey, index) => {
      const axisName = `yaxis${index + 2}`;
      const heightRatio = subchartHeight / totalHeight;

      layoutYAxes[axisName] = {
        domain: [currentBottom, currentBottom + heightRatio - yDomainPadding],
        gridcolor: '#30363d',
        zerolinecolor: '#30363d',
        tickfont: { color: '#8b949e', size: 10 },
        anchor: 'x'
      };

      const [indName, tf] = indTfKey.split('_');
      const tfData = symDisplayed[indName]?.[tf] || {};

      Object.entries(tfData).forEach(([outCol, config]) => {
        if (config.position !== 'subchart') return;
        const df = multiTfData[tf];
        if (!df || !df[outCol] || !df.open_time) return;

        traces.push({
          x: df.open_time.map(safeToISOString),
          y: df[outCol],
          type: config.type === 'bar' ? 'bar' : 'scatter',
          mode: config.type === 'bar' ? undefined : config.type,
          name: `${outCol} (${tf})`,
          yaxis: `y${index + 2}`,
          line: config.type === 'lines' ? { color: config.color, width: config.width } : undefined,
          marker: config.type !== 'lines' ? { color: config.color } : undefined,
          opacity: config.opacity
        });
      });

      currentBottom += heightRatio;
    });

    layoutYAxes['yaxis'] = {
      domain: [currentBottom, 1],
      gridcolor: '#30363d',
      zerolinecolor: '#30363d',
      tickfont: { color: '#8b949e', size: 10 },
      side: 'right',
      anchor: 'x'
    };

    const layout = {
      height: totalHeight,
      margin: { l: 50, r: 50, t: 20, b: 40 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      showlegend: true,
      legend: { orientation: 'h', y: 1.05, font: { color: '#c9d1d9' } },
      xaxis: {
        rangeslider: { visible: false },
        gridcolor: '#30363d',
        zerolinecolor: '#30363d',
        tickfont: { color: '#8b949e', size: 10 },
        type: 'date',
        anchor: 'y'
      },
      ...layoutYAxes,
      hovermode: 'x unified'
    };

    const cleanedTraces = traces.map((t) => {
      const copy = {};
      Object.entries(t).forEach(([k, v]) => {
        if (v !== undefined) {
          copy[k] = v;
        }
      });
      return copy;
    });

    return { traces: cleanedTraces, layout };
  }, [multiTfData, selectedTf, displayedIndicators, activeSymbol]);
};