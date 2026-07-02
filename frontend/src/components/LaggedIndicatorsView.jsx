import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../../store/useAppStore';

const LaggedIndicatorsView = () => {
  const { activeSymbol, activeSession } = useAppStore();
  
  const [lagData, setLagData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const [targetFeature, setTargetFeature] = useState('returns');
  const [isolateTarget, setIsolateTarget] = useState('high_kick');

  useEffect(() => {
    const fetchLaggedData = async () => {
      if (!activeSymbol || !activeSession) return;
      
      setIsLoading(true);
      setError(null);
      
      try {
        // 1. Récupération des données temporelles globales
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
        
        if (!analysisReq.ok) throw new Error('Erreur lors de la récupération des données d\'analyse');
        const analysisRes = await analysisReq.json();
        setAnalysisData(analysisRes);

        // 2. Simulation d'un endpoint spécifique pour les trajectoires retardées (Intégration Tâche 3.2)
        // Dans un cas réel, cet appel pointerait vers un endpoint exposant `compute_lagged_trajectories`
        // Nous utilisons ici les données de base pour construire l'espace des phases 3D en frontend
        const df = analysisRes.timeseries;
        
        const featureSeries = df[targetFeature];
        const mean = featureSeries.reduce((a, b) => a + b, 0) / featureSeries.length;
        const std = Math.sqrt(featureSeries.map(x => Math.pow(x - mean, 2)).reduce((a, b) => a + b) / featureSeries.length);
        const featNorm = featureSeries.map(x => (x - mean) / (std + 1e-8));

        // Downsampling à 1000 points pour la 3D (Performance WebGL)
        const sliceLength = Math.min(featNorm.length - 2, 1000);
        const startIndex = featNorm.length - sliceLength;
        
        const xAtt = featNorm.slice(startIndex, featNorm.length);
        const yAtt = featNorm.slice(startIndex - 1, featNorm.length - 1);
        const zAtt = featNorm.slice(startIndex - 2, featNorm.length - 2);

        // Distances au centroïde pour la couleur
        const cX = xAtt.reduce((a, b) => a + b, 0) / xAtt.length;
        const cY = yAtt.reduce((a, b) => a + b, 0) / yAtt.length;
        const cZ = zAtt.reduce((a, b) => a + b, 0) / zAtt.length;
        
        const distances = xAtt.map((x, i) => 
          Math.sqrt(Math.pow(x - cX, 2) + Math.pow(yAtt[i] - cY, 2) + Math.pow(zAtt[i] - cZ, 2))
        );

        setLagData({ xAtt, yAtt, zAtt, distances });

      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchLaggedData();
  }, [activeSymbol, activeSession, targetFeature]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full p-10 text-[#8b949e]">
        <i className="fa-solid fa-circle-notch fa-spin fa-2x mr-4"></i>
        <span>Calcul matriciel des matrices de corrélation et attracteurs 3D...</span>
      </div>
    );
  }

  if (error) {
    return <div className="p-10 text-[#f85149]">Erreur: {error}</div>;
  }

  if (!lagData || !analysisData) {
    return <div className="p-10 text-[#8b949e]">Veuillez sélectionner un run actif pour afficher l'analyse.</div>;
  }

  return (
    <div className="p-6 space-y-6">
      {/* Panneau de Configuration */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 shadow-sm">
        <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
          <i className="fa-solid fa-sliders mr-2"></i> Configuration des Décalages
        </h3>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <label className="block text-xs text-[#8b949e] uppercase tracking-wider mb-2">Feature d'observation</label>
            <select 
              value={targetFeature}
              onChange={(e) => setTargetFeature(e.target.value)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#58a6ff]"
            >
              <option value="returns">Rendements (Returns)</option>
              <option value="volume">Volume</option>
              <option value="spread">Spread</option>
              <option value="upper_wick">Mèche Haute (Upper Wick)</option>
              <option value="lower_wick">Mèche Basse (Lower Wick)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-[#8b949e] uppercase tracking-wider mb-2">Trajectoire à isoler (CI)</label>
            <select 
              value={isolateTarget}
              onChange={(e) => setIsolateTarget(e.target.value)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#58a6ff]"
            >
              <option value="high_kick">High Kick</option>
              <option value="low_kick">Low Kick</option>
              <option value="normal">Normal</option>
            </select>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Attracteur 3D */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 shadow-sm">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
            <i className="fa-solid fa-cube mr-2"></i> Espace des Phases 3D (Chaos Attractor)
          </h3>
          <div className="h-[400px]">
            <Plot
              data={[{
                type: 'scatter3d',
                mode: 'markers',
                x: lagData.xAtt,
                y: lagData.yAtt,
                z: lagData.zAtt,
                marker: {
                  size: 3,
                  color: lagData.distances,
                  colorscale: 'Viridis',
                  opacity: 0.8
                }
              }]}
              layout={{
                margin: { l: 0, r: 0, t: 0, b: 0 },
                paper_bgcolor: '#161b22',
                scene: {
                  xaxis: { title: 't', gridcolor: '#30363d', backgroundcolor: '#161b22' },
                  yaxis: { title: 't-1', gridcolor: '#30363d', backgroundcolor: '#161b22' },
                  zaxis: { title: 't-2', gridcolor: '#30363d', backgroundcolor: '#161b22' },
                  bgcolor: '#161b22'
                }
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </div>

        {/* Matrice de Corrélation Croisée Dynamique (Heatmap Placeholder) */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 shadow-sm">
          <h3 className="text-[#58a6ff] text-sm font-semibold uppercase tracking-wider mb-4 border-b border-[#30363d] pb-2">
            <i className="fa-solid fa-table-cells mr-2"></i> Matrice de Corrélation Croisée Dynamique
          </h3>
          <div className="h-[400px] flex items-center justify-center text-[#8b949e] border border-dashed border-[#30363d] rounded bg-[#0d1117]">
            <div className="text-center">
              <i className="fa-solid fa-chart-area fa-2x mb-3 text-[#30363d]"></i>
              <p>Heatmap générée dynamiquement via l'API d'analyse croisée.</p>
              <p className="text-xs mt-2 text-[#58a6ff]">Requiert l'activation du module pandas.corr() au niveau du Gateway.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LaggedIndicatorsView;