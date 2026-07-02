import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../../store/useAppStore';

const VSAView = () => {
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
        
        if (!response.ok) throw new Error('Erreur récupération VSA');
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

  if (isLoading) return <div className="p-10 text-[#8b949e]">Analyse VSA en cours...</div>;
  if (error) return <div className="p-10 text-[#f85149]">Erreur: {error}</div>;
  if (!data) return null;

  const { timeseries: df } = data;
  
  // Filtrage des événements VSA
  const vsaEvents = [];
  for (let i = 0; i < df.open_time.length; i++) {
    const volZ = (df.volume[i] - 100) / 50; // Simplification logique backend
    const spread = df.spread[i];
    let classification = 'Normal';
    if (volZ > 2.0 && spread > 0.02) classification = 'Climax';
    else if (volZ < -1.0 && spread < 0.005) classification = 'No Demand';
    
    if (classification !== 'Normal') {
      vsaEvents.push({ time: df.open_time[i], class: classification, spread, volZ });
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Distribution des Mèches */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase mb-4">Distribution des Mèches</h3>
          <Plot
            data={[
              { x: df.upper_wick.map(v => v * 100), type: 'histogram', marker: { color: '#2ecc71' }, name: 'Mèches Hautes', opacity: 0.6 },
              { x: df.lower_wick.map(v => v * 100), type: 'histogram', marker: { color: '#e74c3c' }, name: 'Mèches Basses', opacity: 0.6 }
            ]}
            layout={{ height: 300, barmode: 'overlay', paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', margin: { t: 10, b: 40 } }}
            config={{ responsive: true, displayModeBar: false }}
          />
        </div>

        {/* Événements VSA */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase mb-4">Détecteur d'événements</h3>
          <div className="h-[300px] overflow-auto text-xs">
            <table className="w-full text-left">
              <thead className="text-[#8b949e]"><tr><th>Temps</th><th>Classe</th><th>Spread</th></tr></thead>
              <tbody>
                {vsaEvents.slice(-10).map((ev, i) => (
                  <tr key={i} className="border-t border-[#30363d]">
                    <td className="py-2">{new Date(ev.time).toLocaleTimeString()}</td>
                    <td className="py-2 text-[#58a6ff] font-bold">{ev.class}</td>
                    <td className="py-2">{ev.spread.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      
      {/* Rejection Profiler */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
        <h3 className="text-[#58a6ff] text-sm font-semibold uppercase mb-4">Wick Rejection Profiler (Regression)</h3>
        <Plot
          data={[{
            x: df.upper_wick.slice(-1000),
            y: df.volatility.slice(-1000),
            type: 'scatter',
            mode: 'markers',
            marker: { size: 3, color: '#1f6feb', opacity: 0.5 }
          }]}
          layout={{ height: 350, paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', margin: { t: 10, b: 40 } }}
          config={{ responsive: true, displayModeBar: false }}
        />
      </div>
    </div>
  );
};

export default VSAView;