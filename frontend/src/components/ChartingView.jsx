import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../../store/useAppStore';

const ChartingView = () => {
  const { activeSymbol, activeSession, selectedOverlays, selectedOscillators, indicatorParams } = useAppStore();
  
  const [chartData, setChartData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchChartData = async () => {
      if (!activeSymbol || !activeSession) return;
      
      setIsLoading(true);
      setError(null);
      
      try {
        // 1. Récupération de l'analyse globale (inclut OHLCV et features de base)
        const analysisReq = await fetch('http://localhost:8000/api/analysis/compute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            exchange: 'BINANCE',
            symbol: activeSymbol,
            timeframe: activeSession.timeframe,
            start_time: new Date(activeSession.period_start).getTime(),
            end_time: new Date(activeSession.period_end).getTime(),
            kick_threshold_pct: activeSession.kick_threshold
          })
        });
        
        if (!analysisReq.ok) throw new Error('Erreur lors de la récupération des données OHLCV');
        const analysisData = await analysisReq.json();
        const df = analysisData.timeseries;
        const timeArray = df.open_time.map(t => new Date(t).toISOString());

        // 2. Récupération dynamique des indicateurs (Overlays + Oscillateurs)
        const allIndicators = [...selectedOverlays, ...selectedOscillators];
        const indicatorResults = {};

        // Exécution en parallèle des appels à VectorBT Pro via le Gateway
        await Promise.all(allIndicators.map(async (indName) => {
          const params = indicatorParams[indName] || {};
          const indReq = await fetch('http://localhost:8000/api/indicator/calculate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              func_name: indName,
              exchange: 'BINANCE',
              symbol: activeSymbol,
              timeframe: activeSession.timeframe,
              start_time: new Date(activeSession.period_start).getTime(),
              end_time: new Date(activeSession.period_end).getTime(),
              params: params,
              downcast_float32: true
            })
          });
          
          if (indReq.ok) {
            const indData = await indReq.json();
            indicatorResults[indName] = indData.outputs;
          }
        }));

        setChartData({ timeseries: df, timeArray, indicators: indicatorResults });
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchChartData();
  }, [activeSymbol, activeSession, selectedOverlays, selectedOscillators, indicatorParams]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full p-10 text-[#8b949e]">
        <i className="fa-solid fa-circle-notch fa-spin fa-2x mr-4"></i>
        <span>Calcul vectoriel et génération du graphique en cours...</span>
      </div>
    );
  }

  if (error) {
    return <div className="p-10 text-[#f85149]">Erreur: {error}</div>;
  }

  if (!chartData) {
    return <div className="p-10 text-[#8b949e]">Veuillez sélectionner un run actif pour afficher le graphique.</div>;
  }

  const { timeseries: ts, timeArray, indicators } = chartData;
  const numOscillators = selectedOscillators.length;
  
  // Construction des traces Plotly
  const traces = [];

  // Y1: Trace Candlestick principale
  traces.push({
    x: timeArray,
    open: ts.open,
    high: ts.high,
    low: ts.low,
    close: ts.close,
    type: 'candlestick',
    xaxis: 'x',
    yaxis: 'y',
    name: 'OHLCV',
    increasing: { line: { color: '#2ecc71' } },
    decreasing: { line: { color: '#e74c3c' } }
  });

  // Y1: Superposition des Overlays
  selectedOverlays.forEach(ind => {
    if (indicators[ind]) {
      Object.keys(indicators[ind]).forEach((outName) => {
        traces.push({
          x: timeArray,
          y: indicators[ind][outName],
          type: 'scatter',
          mode: 'lines',
          xaxis: 'x',
          yaxis: 'y',
          name: `${ind} (${outName})`,
          line: { width: 1.5 }
        });
      });
    }
  });

  // Y2: Trace Volume
  const volumeColors = ts.close.map((c, i) => c >= ts.open[i] ? 'rgba(46, 204, 113, 0.5)' : 'rgba(231, 76, 60, 0.5)');
  traces.push({
    x: timeArray,
    y: ts.volume,
    type: 'bar',
    xaxis: 'x',
    yaxis: 'y2',
    name: 'Volume',
    marker: { color: volumeColors }
  });

  // Subplots pour les Oscillateurs (Y3, Y4, etc.)
  selectedOscillators.forEach((ind, index) => {
    const yAxisRef = `y${index + 3}`;
    if (indicators[ind]) {
      Object.keys(indicators[ind]).forEach((outName) => {
        traces.push({
          x: timeArray,
          y: indicators[ind][outName],
          type: 'scatter',
          mode: 'lines',
          xaxis: 'x',
          yaxis: yAxisRef,
          name: `${ind} (${outName})`,
          line: { width: 1.2 }
        });
      });
    }
  });

  // Configuration du layout (Synchronisation stricte)
  const baseHeight = 400;
  const oscHeight = 150;
  const totalHeight = baseHeight + 100 + (numOscillators * oscHeight);

  // Définition des domaines Y
  const yDomainPadding = 0.02;
  const layoutYAxes = {};
  
  // Osc domains (Bottom-up)
  let currentBottom = 0;
  selectedOscillators.forEach((_, index) => {
    const heightRatio = oscHeight / totalHeight;
    layoutYAxes[`yaxis${index + 3}`] = {
      domain: [currentBottom, currentBottom + heightRatio - yDomainPadding],
      gridcolor: '#30363d',
      zerolinecolor: '#30363d',
      tickfont: { color: '#8b949e', size: 10 }
    };
    currentBottom += heightRatio;
  });

  // Volume domain (Just above oscillators)
  const volHeightRatio = 100 / totalHeight;
  layoutYAxes['yaxis2'] = {
    domain: [currentBottom, currentBottom + volHeightRatio - yDomainPadding],
    showticklabels: false,
    gridcolor: 'transparent',
    zerolinecolor: 'transparent'
  };
  currentBottom += volHeightRatio;

  // Main chart domain (Top)
  layoutYAxes['yaxis'] = {
    domain: [currentBottom, 1],
    gridcolor: '#30363d',
    zerolinecolor: '#30363d',
    tickfont: { color: '#8b949e', size: 10 },
    fixedrange: false
  };

  const layout = {
    height: totalHeight,
    margin: { l: 50, r: 20, t: 20, b: 40 },
    paper_bgcolor: '#0d1117',
    plot_bgcolor: '#161b22',
    showlegend: true,
    legend: {
      orientation: 'h',
      y: 1.02,
      font: { color: '#c9d1d9' }
    },
    xaxis: {
      rangeslider: { visible: false },
      gridcolor: '#30363d',
      zerolinecolor: '#30363d',
      tickfont: { color: '#8b949e', size: 10 },
      type: 'date'
    },
    ...layoutYAxes,
    hovermode: 'x unified'
  };

  return (
    <div className="p-6">
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4 shadow-sm">
        <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
          <i className="fa-solid fa-chart-candlestick mr-2"></i> Graphique Principal Vectorisé
        </h3>
        <Plot
          data={traces}
          layout={layout}
          config={{ responsive: true, displayModeBar: false }}
          style={{ width: '100%', height: '100%' }}
        />
      </div>
    </div>
  );
};

export default ChartingView;