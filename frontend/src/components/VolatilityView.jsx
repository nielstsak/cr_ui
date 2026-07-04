import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../store/useAppStore';

const VolatilityView = () => {
  const { activeSymbol, activeSession } = useAppStore();
  const [volData, setVolData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchVolData = async () => {
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
        
        if (!response.ok) throw new Error('Erreur lors de la récupération des données');
        const data = await response.json();
        
        // Calcul manuel côté front des métriques spécifiques basées sur le timeseries reçu
        const df = data.timeseries;
        const probs = data.conditional_probabilities; // p_k, p_k_k1, p_k_k1_k2
        
        // Hurst (simplifié) et Volatility EMA calculés côté backend idéalement ou ici
        setVolData({ probs, df });
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };
    fetchVolData();
  }, [activeSymbol, activeSession]);

  if (isLoading) return <div className="p-10 text-[#8b949e]">Calculs de volatilité en cours...</div>;
  if (error) return <div className="p-10 text-[#f85149]">Erreur: {error}</div>;
  if (!volData) return null;

  const { probs, df } = volData;

  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Persistance des Kicks */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase mb-4">Persistance des Kicks</h3>
          <Plot
            data={[{
              x: ['P(K)', 'P(K|K_t-1)', 'P(K|K_t-1, K_t-2)'],
              y: [probs.p_k, probs.p_k_k1, probs.p_k_k1_k2],
              type: 'bar',
              marker: { color: '#8b949e' }
            }]}
            layout={{ height: 300, paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', margin: { t: 10, b: 40 }, yaxis: { range: [0, 1] } }}
            config={{ responsive: true, displayModeBar: false }}
          />
        </div>

        {/* Hurst Spectrum */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase mb-4">Évolution du Spectre de Hurst</h3>
          <Plot
            data={[{
              x: df.open_time.map(t => new Date(t).toISOString()),
              y: df.hurst || [],
              type: 'scatter',
              mode: 'lines',
              line: { color: '#ffffff', width: 1.5 }
            }]}
            layout={{ height: 300, paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', margin: { t: 10, b: 40 }, yaxis: { range: [0.2, 0.8] } }}
            config={{ responsive: true, displayModeBar: false }}
          />
        </div>
      </div>
    </div>
  );
};

export default VolatilityView;