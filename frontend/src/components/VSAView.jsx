import React, { useEffect, useState, useMemo } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../store/useAppStore.js';

/**
 * Composant VSAView - Analyse du Volume Spread Analysis (VSA) et comportement géométrique des mèches.
 * Implémente l'analyse de dispersion 2D, l'estimation des deltas de volumes absorbés,
 * et la régression linéaire sur le profil de rejet des mèches.
 */
const VSAView = () => {
  const activeSymbol = useAppStore((state) => state.activeSymbol);
  const activeSession = useAppStore((state) => state.activeSession);
  
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!activeSymbol || !activeSession) return;
    
    setIsLoading(true);
    setError(null);

    fetch('http://localhost:8000/api/analysis/compute', {
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
    })
    .then((r) => {
      if (!r.ok) throw new Error("Impossible de récupérer les métriques d'analyse VSA du serveur.");
      return r.json();
    })
    .then((res) => setData(res))
    .catch((err) => setError(err.message))
    .finally(() => setIsLoading(false));
  }, [activeSymbol, activeSession]);

  // Traitement statistique vectoriel des métriques d'absorption (VSA & Mèches)
  const vsaMetrics = useMemo(() => {
    if (!data || !data.timeseries) return null;
    
    const df = data.timeseries;
    const n = df.open_time.length;

    // 1. Calcul causal du Z-Score de Volume local
    const meanVol = df.volume.reduce((a, b) => a + b, 0) / n;
    const stdVol = Math.sqrt(df.volume.map(v => Math.pow(v - meanVol, 2)).reduce((a, b) => a + b, 0) / n) || 1e-8;
    const volZScores = df.volume.map(v => (v - meanVol) / stdVol);

    // 2. Calcul des quantiles de Spread pour isoler les anomalies géométriques
    const sortedSpreads = [...df.spread].sort((a, b) => a - b);
    const q15 = sortedSpreads[Math.floor(n * 0.15)] || 0;
    const q40 = sortedSpreads[Math.floor(n * 0.40)] || 0;
    const q85 = sortedSpreads[Math.floor(n * 0.85)] || 0;

    // 3. Classification selon la méthodologie Volume Spread Analysis (VSA)
    const events = [];
    const netWickVols = [];
    const xReg = [];
    const yReg = [];

    for (let i = 0; i < n; i++) {
      const volZ = volZScores[i];
      const spread = df.spread[i];
      const upperWick = df.upper_wick[i];
      const lowerWick = df.lower_wick[i];
      const body = df.body_size[i];
      const vol = df.volume[i];
      const volatility = df.volatility[i] || 0;
      
      let classification = 'Normal';
      if (volZ > 2.0 && spread > q85) {
        classification = 'Climax';
      } else if (volZ < -1.0 && spread < q15) {
        classification = 'No Demand';
      } else if (volZ > 2.0 && spread < q40) {
        classification = 'Effort vs Result';
      }

      if (classification !== 'Normal') {
        events.push({
          time: new Date(df.open_time[i]).toISOString().replace('T', ' ').substring(0, 19),
          classification,
          spread: spread.toFixed(5),
          volZ: volZ.toFixed(2),
          wick: (upperWick * 100).toFixed(3)
        });
      }

      // Calcul du volume net absorbé par les mèches
      netWickVols.push(vol * (upperWick - lowerWick));

      // Ratio Mèche/Corps vs Volatilité pour modéliser le rejet
      const ratio = upperWick / (body + 1e-8);
      if (isFinite(ratio) && ratio < 20) {
        xReg.push(ratio);
        yReg.push(volatility * 100);
      }
    }

    // Régression linéaire : Ratio de Rejet des Mèches vs Volatilité locale
    let regLineX = [];
    let regLineY = [];
    if (xReg.length > 1) {
      const len = xReg.length;
      const sumX = xReg.reduce((a, b) => a + b, 0);
      const sumY = yReg.reduce((a, b) => a + b, 0);
      const sumXY = xReg.reduce((sum, x, idx) => sum + x * yReg[idx], 0);
      const sumX2 = xReg.reduce((sum, x) => sum + x * x, 0);
      
      const slope = (len * sumXY - sumX * sumY) / (len * sumX2 - sumX * sumX || 1e-8);
      const intercept = (sumY - slope * sumX) / len;

      const minX = Math.min(...xReg);
      const maxX = Math.max(...xReg);
      regLineX = [minX, maxX];
      regLineY = [slope * minX + intercept, slope * maxX + intercept];
    }

    return {
      volZScores,
      events: events.reverse(), // Du plus récent au plus ancien
      netWickVols,
      xReg,
      yReg,
      regLineX,
      regLineY
    };
  }, [data]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-[#8b949e] text-sm">
        <i className="fa-solid fa-circle-notch fa-spin mr-3 text-brand-500"></i>
        Analyse VSA et des dynamiques de rejet en cours...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-[#161b22] border border-red-950 text-red-400 rounded-lg text-xs font-mono">
        <i className="fa-solid fa-triangle-exclamation mr-2"></i> Erreur : {error}
      </div>
    );
  }

  if (!data || !vsaMetrics) {
    return (
      <div className="p-10 text-center text-[#8b949e] text-xs font-mono">
        Aucun run de données actif détecté. Sélectionnez une session d'analyse pour afficher les graphiques.
      </div>
    );
  }

  const { timeseries: df } = data;
  const last100Times = df.open_time.slice(-100).map(t => new Date(t).toISOString());
  const last100NetWicks = vsaMetrics.netWickVols.slice(-100);
  const netWickColors = last100NetWicks.map(v => v >= 0 ? '#2ecc71' : '#e74c3c');

  return (
    <div className="p-6 space-y-6">
      
      {/* Ligne 1 : Histogramme de distribution des mèches & Tableau VSA */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Histogramme de répartition géométrique */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
          <h3 className="text-white text-xs font-bold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2 flex items-center">
            <i className="fa-solid fa-chart-simple mr-2 text-brand-500"></i> Distribution Statistique des Mèches
          </h3>
          <div className="h-[300px]">
            <Plot
              data={[
                { x: df.upper_wick.map(v => v * 100), type: 'histogram', name: 'Mèches Hautes', marker: { color: '#2ecc71' }, opacity: 0.6 },
                { x: df.lower_wick.map(v => v * 100), type: 'histogram', name: 'Mèches Basses', marker: { color: '#e74c3c' }, opacity: 0.6 }
              ]}
              layout={{
                barmode: 'overlay',
                paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
                margin: { t: 10, b: 40, l: 40, r: 10 },
                xaxis: { title: 'Taille de la mèche (%)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                yaxis: { title: 'Fréquence', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                legend: { font: { color: '#c9d1d9' }, orientation: 'h', y: 1.15 }
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </div>

        {/* Tableau de classification et d'occurrences VSA */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm flex flex-col justify-between">
          <h3 className="text-white text-xs font-bold uppercase tracking-wider mb-3 border-b border-[#30363d] pb-2 flex items-center">
            <i className="fa-solid fa-bolt mr-2 text-[#58a6ff]"></i> Détecteur d'Anomalies de Trading VSA
          </h3>
          <div className="flex-1 overflow-y-auto max-h-[250px] pr-1">
            {vsaMetrics.events.length === 0 ? (
              <div className="text-center py-16 text-[#8b949e] text-xs font-mono">Aucun événement VSA détecté dans cette session.</div>
            ) : (
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="text-gray-500 border-b border-[#30363d] text-[10px] uppercase">
                    <th className="py-2">Date (UTC)</th>
                    <th className="py-2">État VSA</th>
                    <th className="py-2">Spread</th>
                    <th className="py-2">Volume (Z)</th>
                    <th className="py-2">Mèche (%)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#30363d] text-gray-300">
                  {vsaMetrics.events.slice(0, 15).map((ev, idx) => (
                    <tr key={idx} className="hover:bg-[#0d1117]/30 transition-colors">
                      <td className="py-2 text-[11px] text-gray-400">{ev.time}</td>
                      <td className={`py-2 font-bold ${
                        ev.classification === 'Climax' ? 'text-[#2ecc71]' : ev.classification === 'No Demand' ? 'text-[#e74c3c]' : 'text-brand-500'
                      }`}>{ev.classification}</td>
                      <td className="py-2">{ev.spread}</td>
                      <td className="py-2">{ev.volZ}</td>
                      <td className="py-2">{ev.wick}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Ligne 2 : Densité d'absorption 2D & Delta Volume */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Densité 2D Contour */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
          <h3 className="text-white text-xs font-bold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2 flex items-center">
            <i className="fa-solid fa-circle-nodes mr-2 text-[#58a6ff]"></i> Analyse bidimensionnelle Mèches / Volume (Z-Score)
          </h3>
          <div className="h-[320px]">
            <Plot
              data={[
                {
                  x: df.upper_wick.map(v => v * 100),
                  y: vsaMetrics.volZScores,
                  mode: 'markers',
                  type: 'scatter',
                  marker: { color: 'rgba(139, 148, 158, 0.4)', size: 4 },
                  name: 'Observations'
                },
                {
                  x: df.upper_wick.map(v => v * 100),
                  y: vsaMetrics.volZScores,
                  type: 'histogram2dcontour',
                  colorscale: 'Blues',
                  ncontours: 20,
                  contours: { coloring: 'none', showlabels: false }
                }
              ]}
              layout={{
                paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
                margin: { t: 10, b: 40, l: 40, r: 10 },
                xaxis: { title: 'Taille Mèche (%)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                yaxis: { title: 'Z-Score de Volume', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                showlegend: false
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </div>

        {/* Delta Volume Absorbé par les mèches */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
          <h3 className="text-white text-xs font-bold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2 flex items-center">
            <i className="fa-solid fa-scale-balanced mr-2 text-[#58a6ff]"></i> Volume Net Absorbé par les Mèches (Haut vs Bas)
          </h3>
          <div className="h-[320px]">
            <Plot
              data={[{
                x: last100Times,
                y: last100NetWicks,
                type: 'bar',
                marker: { color: netWickColors },
                name: 'Net Wick Volume'
              }]}
              layout={{
                paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
                margin: { t: 10, b: 40, l: 50, r: 10 },
                xaxis: { type: 'date', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                yaxis: { title: 'Delta volume absorbé (Unité brute)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } }
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </div>
      </div>

      {/* Ligne 3 : Modélisation mathématique du rejet des mèches */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
        <h3 className="text-white text-xs font-bold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2 flex items-center">
          <i className="fa-solid fa-chart-line mr-2 text-[#58a6ff]"></i> Modélisation Mathématique de Rejet (Régression Linéaire)
        </h3>
        <div className="h-[350px]">
          <Plot
            data={[
              {
                x: vsaMetrics.xReg.slice(-1500),
                y: vsaMetrics.yReg.slice(-1500),
                mode: 'markers',
                type: 'scatter',
                marker: { color: '#1f6feb', size: 4, opacity: 0.5 },
                name: 'Données Observées (Mèche / Taille Corps)'
              },
              {
                x: vsaMetrics.regLineX,
                y: vsaMetrics.regLineY,
                mode: 'lines',
                type: 'scatter',
                line: { color: '#e74c3c', width: 2.5 },
                name: 'Modèle de régression linéaire'
              }
            ]}
            layout={{
              paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
              margin: { t: 10, b: 40, l: 50, r: 10 },
              xaxis: { title: 'Ratio Géométrique (Mèche / Corps)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
              yaxis: { title: 'Volatilité locale mesurée (%)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
              legend: { font: { color: '#c9d1d9' }, orientation: 'h', y: 1.1 }
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      </div>

    </div>
  );
};

export default VSAView;