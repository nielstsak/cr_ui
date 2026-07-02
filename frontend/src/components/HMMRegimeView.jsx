import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../../store/useAppStore';

const HMMRegimeView = () => {
  const { activeSymbol, activeSession } = useAppStore();
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      if (!activeSymbol || !activeSession) return;
      setIsLoading(true);
      try {
        const response = await fetch('http://localhost:8000/api/analysis/compute', {
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
        
        if (!response.ok) throw new Error('Erreur récupération HMM');
        const res = await response.json();
        setData(res);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };
    fetchData();
  }, [activeSymbol, activeSession]);

  if (isLoading) return <div className="p-10 text-[#8b949e]">Calcul des régimes HMM...</div>;
  if (error) return <div className="p-10 text-[#f85149]">Erreur: {error}</div>;
  if (!data) return null;

  const { timeseries: df, pca_clusters: pca } = data;
  const states = df.ordered_regime;
  const times = df.open_time.map(t => new Date(t).toISOString());
  const regColors = { 0: 'rgba(46, 204, 113, 0.15)', 1: 'rgba(231, 76, 60, 0.15)', 2: 'rgba(139, 148, 158, 0.15)' };

  const shapes = [];
  let currState = states[0];
  let startTime = times[0];
  for (let i = 1; i < states.length; i++) {
    if (states[i] !== currState) {
      shapes.push({ type: 'rect', x0: startTime, x1: times[i-1], fillcolor: regColors[currState], line: { width: 0 } });
      currState = states[i];
      startTime = times[i];
    }
  }
  shapes.push({ type: 'rect', x0: startTime, x1: times[times.length-1], fillcolor: regColors[currState], line: { width: 0 } });

  return (
    <div className="p-6 space-y-6">
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
        <h3 className="text-[#58a6ff] text-sm font-semibold uppercase mb-4">Prix et Régimes HMM</h3>
        <Plot
          data={[{ x: times, y: df.close, type: 'scatter', mode: 'lines', line: { color: '#ffffff', width: 1.5 } }]}
          layout={{
            height: 350, paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', margin: { t: 10, b: 40 },
            shapes: shapes,
            xaxis: { gridcolor: '#30363d' }, yaxis: { gridcolor: '#30363d' }
          }}
          config={{ responsive: true, displayModeBar: false }}
        />
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase mb-4">PCA 2D des Clusters</h3>
          <Plot
            data={[0, 1, 2].map(r => ({
              x: pca[r]?.pc1 || [],
              y: pca[r]?.pc2 || [],
              type: 'scatter',
              mode: 'markers',
              name: ['Hausse', 'Baisse', 'Stagnation'][r],
              marker: { size: 5, color: ['#2ecc71', '#e74c3c', '#8b949e'][r] }
            }))}
            layout={{ height: 300, paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', margin: { t: 10, b: 40 }, xaxis: { gridcolor: '#30363d' }, yaxis: { gridcolor: '#30363d' } }}
            config={{ responsive: true, displayModeBar: false }}
          />
        </div>
      </div>
    </div>
  );
};

export default HMMRegimeView;