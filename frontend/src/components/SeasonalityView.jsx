import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../../store/useAppStore';

const DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const SeasonalityView = () => {
  const { activeSymbol, activeSession } = useAppStore();
  
  const [seasonalityData, setSeasonalityData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchSeasonalityData = async () => {
      if (!activeSymbol || !activeSession) return;
      
      setIsLoading(true);
      setError(null);
      
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
        
        if (!response.ok) throw new Error('Erreur lors de la récupération des données d\'analyse');
        const data = await response.json();
        const df = data.timeseries;
        
        // ---------------------------------------------------------
        // Agrégations JavaScript (remplacement de Pandas)
        // ---------------------------------------------------------
        
        // 1. Préparation des données enrichies
        const enriched = df.open_time.map((t, i) => {
          const date = new Date(t);
          const hour = date.getUTCHours();
          let session = 'US';
          if (hour >= 0 && hour < 8) session = 'Asie';
          if (hour >= 8 && hour < 16) session = 'Europe';

          return {
            hour,
            day: DAYS_OF_WEEK[date.getUTCDay()],
            month: MONTHS[date.getUTCMonth()],
            session,
            isKick: ['High Kick', 'Low Kick', 'Both'].includes(df.kick_type[i]) ? 1 : 0,
            upperWick: df.upper_wick[i],
            lowerWick: df.lower_wick[i],
            returns: df.returns[i],
            volume: df.volume[i],
            spread: df.spread[i],
            bodySize: df.body_size[i]
          };
        });

        // 2. Heatmap (Jour vs Heure -> Fréquence des Kicks)
        const heatmapGrid = Array(7).fill(0).map(() => Array(24).fill(0));
        const heatmapCounts = Array(7).fill(0).map(() => Array(24).fill(0));
        
        enriched.forEach(row => {
          const dIdx = (DAYS_OF_WEEK.indexOf(row.day) + 6) % 7; // Lundi = 0, Dimanche = 6
          heatmapGrid[dIdx][row.hour] += row.isKick;
          heatmapCounts[dIdx][row.hour] += 1;
        });

        const hmZ = heatmapGrid.map((row, i) => 
          row.map((val, j) => heatmapCounts[i][j] > 0 ? val / heatmapCounts[i][j] : 0)
        );
        const hmY = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
        const hmX = Array(24).fill(0).map((_, i) => `${i.toString().padStart(2, '0')}:00`);

        // 3. Profil Intra-journalier des Mèches
        const wicksByHour = Array(24).fill(0).map(() => ({ up: 0, low: 0, count: 0 }));
        enriched.forEach(row => {
          wicksByHour[row.hour].up += row.upperWick;
          wicksByHour[row.hour].low += row.lowerWick;
          wicksByHour[row.hour].count += 1;
        });
        const hourX = Array(24).fill(0).map((_, i) => i);
        const wickUpY = wicksByHour.map(w => w.count > 0 ? (w.up / w.count) * 100 : 0);
        const wickLowY = wicksByHour.map(w => w.count > 0 ? (w.low / w.count) * 100 : 0);

        // 4. Boxplots Mensuels (Rendements absolus)
        const returnsByMonth = {};
        enriched.forEach(row => {
          if (!returnsByMonth[row.month]) returnsByMonth[row.month] = [];
          if (row.returns !== null) returnsByMonth[row.month].push(Math.abs(row.returns) * 100);
        });

        // 5. Radar (Sessions)
        const normalize = (arr) => {
          const min = Math.min(...arr);
          const max = Math.max(...arr);
          return arr.map(v => (v - min) / (max - min + 1e-8));
        };

        const normVols = normalize(enriched.map(r => r.volume));
        const normSpreads = normalize(enriched.map(r => r.spread));
        const normUpWicks = normalize(enriched.map(r => r.upperWick));
        const normLowWicks = normalize(enriched.map(r => r.lowerWick));
        const normBodies = normalize(enriched.map(r => r.bodySize));

        const sessionAgg = { 'Asie': [0,0,0,0,0], 'Europe': [0,0,0,0,0], 'US': [0,0,0,0,0] };
        const sessionCounts = { 'Asie': 0, 'Europe': 0, 'US': 0 };

        enriched.forEach((row, i) => {
          sessionAgg[row.session][0] += normVols[i];
          sessionAgg[row.session][1] += normSpreads[i];
          sessionAgg[row.session][2] += normUpWicks[i];
          sessionAgg[row.session][3] += normLowWicks[i];
          sessionAgg[row.session][4] += normBodies[i];
          sessionCounts[row.session] += 1;
        });

        const radarData = Object.keys(sessionAgg).map(sess => {
          const count = sessionCounts[sess] || 1;
          const means = sessionAgg[sess].map(v => v / count);
          means.push(means[0]); // Fermer le polygone
          return { name: sess, r: means };
        });

        setSeasonalityData({ hmX, hmY, hmZ, hourX, wickUpY, wickLowY, returnsByMonth, radarData });

      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchSeasonalityData();
  }, [activeSymbol, activeSession]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full p-10 text-[#8b949e]">
        <i className="fa-solid fa-circle-notch fa-spin fa-2x mr-4"></i>
        <span>Agrégation des données saisonnières en cours...</span>
      </div>
    );
  }

  if (error) {
    return <div className="p-10 text-[#f85149]">Erreur: {error}</div>;
  }

  if (!seasonalityData) {
    return <div className="p-10 text-[#8b949e]">Veuillez sélectionner un run actif pour afficher l'analyse.</div>;
  }

  const { hmX, hmY, hmZ, hourX, wickUpY, wickLowY, returnsByMonth, radarData } = seasonalityData;

  const radarVars = ['Volume', 'Spread', 'Upper Wick', 'Lower Wick', 'Body Size', 'Volume'];
  const radarColors = {
    'Asie': { line: '#f1c40f', fill: 'rgba(241, 196, 15, 0.4)' },
    'Europe': { line: '#1f6feb', fill: 'rgba(31, 111, 235, 0.4)' },
    'US': { line: '#e74c3c', fill: 'rgba(231, 76, 60, 0.4)' }
  };

  return (
    <div className="p-6 space-y-6">
      
      {/* Heatmap */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 shadow-sm">
        <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
          <i className="fa-solid fa-fire mr-2"></i> Heatmap Horaire & Hebdomadaire (Fréquence Kicks)
        </h3>
        <div className="h-[320px]">
          <Plot
            data={[{
              z: hmZ, x: hmX, y: hmY,
              type: 'heatmap',
              colorscale: [[0, '#0d1117'], [1, '#e74c3c']],
              zmin: 0
            }]}
            layout={{
              margin: { l: 80, r: 20, t: 20, b: 40 },
              paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
              xaxis: { title: 'Heure (UTC)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
              yaxis: { gridcolor: '#30363d', tickfont: { color: '#8b949e' } }
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Wick Profile */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 shadow-sm">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
            <i className="fa-solid fa-arrows-up-down mr-2"></i> Profil Intra-Journalier des Mèches
          </h3>
          <div className="h-[300px]">
            <Plot
              data={[
                { x: hourX, y: wickUpY, type: 'scatter', mode: 'lines', line: { color: '#2ecc71', width: 2 }, name: 'Mèches Hautes' },
                { x: hourX, y: wickLowY, type: 'scatter', mode: 'lines', line: { color: '#e74c3c', width: 2 }, name: 'Mèches Basses' }
              ]}
              layout={{
                margin: { l: 40, r: 20, t: 20, b: 40 },
                paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', showlegend: true,
                xaxis: { title: 'Heures de la journée (UTC)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                yaxis: { title: 'Mèche moyenne (%)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                legend: { orientation: 'h', y: 1.1, font: { color: '#c9d1d9' } }
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </div>

        {/* Radar Sessions */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 shadow-sm">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
            <i className="fa-solid fa-radar mr-2"></i> Radar des Signatures Temporelles
          </h3>
          <div className="h-[300px]">
            <Plot
              data={radarData.map(d => ({
                type: 'scatterpolar',
                r: d.r,
                theta: radarVars,
                fill: 'toself',
                name: d.name,
                fillcolor: radarColors[d.name].fill,
                line: { color: radarColors[d.name].line, width: 2 }
              }))}
              layout={{
                margin: { l: 40, r: 40, t: 20, b: 20 },
                paper_bgcolor: '#161b22',
                polar: {
                  bgcolor: '#161b22',
                  radialaxis: { visible: true, range: [0, 1], gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
                  angularaxis: { gridcolor: '#30363d', tickfont: { color: '#c9d1d9' } }
                },
                showlegend: true,
                legend: { orientation: 'h', y: -0.1, font: { color: '#c9d1d9' } }
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </div>

      </div>

      {/* Boxplots Mensuels */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 shadow-sm">
        <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
          <i className="fa-regular fa-calendar mr-2"></i> Boxplots Mensuels de Dispersion
        </h3>
        <div className="h-[320px]">
          <Plot
            data={MONTHS.filter(m => returnsByMonth[m]).map(m => ({
              y: returnsByMonth[m],
              type: 'box',
              name: m,
              boxpoints: 'outliers',
              fillcolor: '#161b22',
              line: { color: '#1f6feb', width: 1.5 }
            }))}
            layout={{
              margin: { l: 40, r: 20, t: 20, b: 40 },
              paper_bgcolor: '#161b22', plot_bgcolor: '#161b22', showlegend: false,
              xaxis: { gridcolor: '#30363d', tickfont: { color: '#8b949e' } },
              yaxis: { title: 'Rendement absolu (%)', gridcolor: '#30363d', tickfont: { color: '#8b949e' } }
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      </div>

    </div>
  );
};

export default SeasonalityView;