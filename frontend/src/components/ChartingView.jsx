import React, { useEffect, useState, useMemo } from 'react';
import Plot from 'react-plotly.js';
import useAppStore from '../store/useAppStore';
import IndicatorManager from './IndicatorManager';

// ==========================================
// SOUS-COMPOSANT 1 : SÉLECTEUR DE SYMBOLE
// ==========================================
const SymbolSelector = ({ localPairs, selectedSymbol, onSelect }) => (
  <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
    <label className="block text-xs font-bold text-[#8b949e] uppercase tracking-wider mb-3 flex items-center">
      <i className="fa-solid fa-magnifying-glass-chart mr-2 text-[#58a6ff]"></i> 
      1. Sélection du Symbole Local
    </label>
    <select
      value={selectedSymbol}
      onChange={(e) => onSelect(e.target.value)}
      className="w-full md:w-1/3 bg-[#0d1117] border border-[#30363d] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono cursor-pointer shadow-inner"
    >
      <option value="" disabled>-- Sélectionnez un symbole --</option>
      {localPairs.map(p => (
        <option key={p.symbol} value={p.symbol}>{p.symbol}</option>
      ))}
    </select>
  </div>
);

// ==========================================
// SOUS-COMPOSANT 2 : GESTIONNAIRE DE TIMEFRAMES
// ==========================================
const ResamplePanel = ({ availableTfs, selectedSymbol }) => {
  const [input, setInput] = useState('');
  const [isResampling, setIsResampling] = useState(false);
  const addTimeframe = useAppStore(state => state.addTimeframe);

  const handleResample = async () => {
    if (!input.trim() || !selectedSymbol) return;
    setIsResampling(true);
    const tfs = input.split(';').map(s => s.trim()).filter(Boolean);
    for (const tf of tfs) {
      await addTimeframe(selectedSymbol, tf);
    }
    setInput('');
    setIsResampling(false);
  };

  const baseTf = availableTfs.includes('5m') ? '5m' : (availableTfs[0] || 'N/A');

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm space-y-4">
        <h4 className="text-white text-xs font-bold uppercase tracking-wider border-b border-[#30363d] pb-2 text-[#58a6ff]">
          <i className="fa-solid fa-clock mr-2"></i> Timeframes Actuels
        </h4>
        <div className="flex justify-between items-center text-sm bg-[#0d1117] border border-[#30363d] p-3 rounded-lg">
          <span className="text-[#8b949e] font-semibold">Timeframe de Base :</span>
          <span className="text-white font-mono font-bold bg-[#1f6feb]/20 text-[#58a6ff] px-2 py-0.5 rounded border border-[#1f6feb]/30">{baseTf}</span>
        </div>
        <div className="flex justify-between items-center text-sm bg-[#0d1117] border border-[#30363d] p-3 rounded-lg">
          <span className="text-[#8b949e] font-semibold">Présents sur le disque :</span>
          <span className="text-white font-mono text-xs text-right break-words pl-4">{availableTfs.join(', ') || 'Aucun'}</span>
        </div>
      </div>

      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm flex flex-col justify-between space-y-3">
        <div>
          <h4 className="text-white text-xs font-bold uppercase tracking-wider border-b border-[#30363d] pb-2 text-[#58a6ff]">
            <i className="fa-solid fa-layer-group mr-2"></i> Resample Base Timeframe
          </h4>
          <p className="text-xs text-gray-500 mt-2">Générez des TF supérieurs. Séparateur "<strong className="text-gray-300">;</strong>" (ex: <span className="font-mono">15m; 1h</span>).</p>
        </div>
        <div className="flex space-x-3">
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)} placeholder="15m; 1h; 4h" className="flex-1 bg-[#0d1117] border border-[#30363d] rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono shadow-inner" />
          <button onClick={handleResample} disabled={isResampling || !input.trim()} className="px-5 py-2 bg-[#1f6feb] hover:bg-[#388bfd] disabled:opacity-50 text-white text-xs font-bold uppercase rounded-lg transition-colors shadow-sm whitespace-nowrap flex items-center">
            {isResampling ? <><i className="fa-solid fa-circle-notch fa-spin mr-2"></i> En cours...</> : 'Activer Resample'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ==========================================
// MODALE D'APPARENCE DES INDICATEURS
// ==========================================
const IndicatorVisualsModal = ({ isOpen, onClose, selectedSymbol, availableTfs }) => {
  const rawCalculated = useAppStore(state => state.calculatedIndicators)[selectedSymbol];
  const calcStr = JSON.stringify(rawCalculated || []);
  const calculatedIndicators = useMemo(() => JSON.parse(calcStr), [calcStr]);

  const displayedIndicators = useAppStore(state => state.displayedIndicators)[selectedSymbol] || {};
  const toggleIndicatorOutput = useAppStore(state => state.toggleIndicatorOutput);
  const updateIndicatorOutputConfig = useAppStore(state => state.updateIndicatorOutputConfig);
  const fetchIndicatorMetadata = useAppStore(state => state.fetchIndicatorMetadata);
  const indicatorMetadata = useAppStore(state => state.indicatorMetadata);

  useEffect(() => {
    if (isOpen) {
      calculatedIndicators.forEach(ind => {
        if (!indicatorMetadata[ind]) fetchIndicatorMetadata(ind);
      });
    }
  }, [isOpen, calculatedIndicators, indicatorMetadata, fetchIndicatorMetadata]);

  if (!isOpen) return null;

  const getExpectedColumns = (indName) => {
    const meta = indicatorMetadata[indName];
    if (!meta || !meta.outputs) return [indName.toUpperCase()];
    if (meta.outputs.length === 1) return [indName.toUpperCase()];
    return meta.outputs.map(out => `${indName.toUpperCase()}_${out.toUpperCase()}`);
  };

  const getAutoColor = (index) => {
    const colors = ['#58a6ff', '#e67e22', '#e74c3c', '#9b59b6', '#2ecc71'];
    return colors[index % colors.length];
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70 backdrop-blur-sm">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl w-[1000px] max-h-[85vh] flex flex-col">
        <div className="flex justify-between items-center p-5 border-b border-[#30363d]">
          <h2 className="text-[#58a6ff] font-bold uppercase tracking-wider text-sm">
            <i className="fa-solid fa-palette mr-2"></i> Affichage Multi-TF des Indicateurs
          </h2>
          <button onClick={onClose} className="text-[#8b949e] hover:text-white"><i className="fa-solid fa-xmark text-lg"></i></button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {calculatedIndicators.length === 0 ? (
            <div className="text-center py-10 text-gray-500 text-xs italic">
              Aucun indicateur n'a été calculé pour ce symbole.
            </div>
          ) : (
            calculatedIndicators.map(ind => {
              const expectedColumns = getExpectedColumns(ind);
              
              return (
                <div key={ind} className="bg-[#0d1117] border border-[#30363d] rounded-xl overflow-hidden shadow-inner">
                  <div className="bg-[#1f6feb]/10 px-5 py-3 border-b border-[#30363d]">
                    <h3 className="text-white font-bold font-mono text-lg">{ind}</h3>
                  </div>
                  
                  <div className="p-4 space-y-6">
                    {availableTfs.map(tf => {
                      return (
                        <div key={`${ind}-${tf}`} className="border-l-2 border-[#58a6ff] pl-4 space-y-3">
                          <h4 className="text-[#8b949e] font-bold text-xs uppercase tracking-wider">Timeframe : <span className="text-[#58a6ff]">{tf}</span></h4>
                          
                          <div className="space-y-3">
                            {expectedColumns.map((colName, cIdx) => {
                              const isDisplayed = !!displayedIndicators[ind]?.[tf]?.[colName];
                              const config = displayedIndicators[ind]?.[tf]?.[colName] || {};
                              
                              const defaultConfig = {
                                color: getAutoColor(cIdx),
                                position: 'subchart',
                                type: colName.includes('HIST') ? 'bar' : 'lines',
                                width: 1.5,
                                opacity: 1
                              };

                              return (
                                <div key={colName} className={`p-3 rounded-lg border transition-colors ${isDisplayed ? 'bg-[#161b22] border-[#1f6feb]/50' : 'bg-[#0d1117] border-[#30363d]'}`}>
                                  <div className="flex items-center space-x-3 mb-2">
                                    <input 
                                      type="checkbox" 
                                      checked={isDisplayed}
                                      onChange={() => toggleIndicatorOutput(selectedSymbol, ind, tf, colName, defaultConfig)}
                                      className="rounded bg-[#161b22] border-[#30363d] text-[#1f6feb] cursor-pointer w-4 h-4"
                                    />
                                    <span className="text-sm font-mono text-white font-semibold">{colName}</span>
                                  </div>

                                  {isDisplayed && (
                                    <div className="grid grid-cols-5 gap-4 mt-3 pt-3 border-t border-[#30363d]">
                                      <div>
                                        <label className="block text-[10px] text-gray-500 uppercase mb-1">Couleur</label>
                                        <input type="color" value={config.color} onChange={e => updateIndicatorOutputConfig(selectedSymbol, ind, tf, colName, 'color', e.target.value)} className="w-full h-7 bg-transparent cursor-pointer rounded" />
                                      </div>
                                      <div>
                                        <label className="block text-[10px] text-gray-500 uppercase mb-1">Position</label>
                                        <select value={config.position} onChange={e => updateIndicatorOutputConfig(selectedSymbol, ind, tf, colName, 'position', e.target.value)} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-2 py-1.5 text-xs text-white">
                                          <option value="overlay">Sur le prix</option>
                                          <option value="subchart">Sous le prix</option>
                                        </select>
                                      </div>
                                      <div>
                                        <label className="block text-[10px] text-gray-500 uppercase mb-1">Type de tracé</label>
                                        <select value={config.type} onChange={e => updateIndicatorOutputConfig(selectedSymbol, ind, tf, colName, 'type', e.target.value)} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-2 py-1.5 text-xs text-white">
                                          <option value="lines">Ligne continue</option>
                                          <option value="bar">Histogramme (Barres)</option>
                                          <option value="markers">Nuage de points</option>
                                        </select>
                                      </div>
                                      <div>
                                        <label className="block text-[10px] text-gray-500 uppercase mb-1">Épaisseur ({config.width})</label>
                                        <input type="range" min="0.5" max="5" step="0.5" value={config.width} onChange={e => updateIndicatorOutputConfig(selectedSymbol, ind, tf, colName, 'width', parseFloat(e.target.value))} className="w-full cursor-pointer accent-[#1f6feb] mt-2" />
                                      </div>
                                      <div>
                                        <label className="block text-[10px] text-gray-500 uppercase mb-1">Opacité ({config.opacity})</label>
                                        <input type="range" min="0.1" max="1" step="0.1" value={config.opacity} onChange={e => updateIndicatorOutputConfig(selectedSymbol, ind, tf, colName, 'opacity', parseFloat(e.target.value))} className="w-full cursor-pointer accent-[#1f6feb] mt-2" />
                                      </div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })
          )}
        </div>
        
        {/* NOUVEAU BOUTON D'ACTUALISATION */}
        <div className="p-4 border-t border-[#30363d] flex justify-end bg-[#0d1117] rounded-b-xl">
          <button 
            onClick={onClose} 
            className="px-6 py-2 bg-[#1f6feb] hover:bg-[#388bfd] text-white text-xs font-bold uppercase rounded-lg shadow-sm transition-colors"
          >
            Valider et Actualiser le Graphique
          </button>
        </div>
      </div>
    </div>
  );
};


// ==========================================
// SOUS-COMPOSANT 3 : GRAPHIQUE OHLCV
// ==========================================
const OhlcvChart = ({ availableTfs, descStats, selectedSymbol }) => {
  const [selectedTf, setSelectedTf] = useState('');
  const [multiTfData, setMultiTfData] = useState({});
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [isVisualsModalOpen, setIsVisualsModalOpen] = useState(false);
  
  const rawDisplayed = useAppStore(state => state.displayedIndicators)[selectedSymbol];
  const dispStr = JSON.stringify(rawDisplayed || {});
  const displayedIndicators = useMemo(() => JSON.parse(dispStr), [dispStr]);
  
  const isGlobalLoading = useAppStore(state => state.isLoading);

  useEffect(() => {
    if (!selectedTf && availableTfs.length > 0) {
      setSelectedTf(availableTfs.includes('5m') ? '5m' : availableTfs[0]);
    }
  }, [availableTfs, selectedTf]);

  const activeTfsSignature = useMemo(() => {
    const tfs = new Set();
    if (selectedTf) tfs.add(selectedTf);
    Object.values(displayedIndicators).forEach(indData => {
      Object.keys(indData).forEach(tf => tfs.add(tf));
    });
    return Array.from(tfs).sort().join(',');
  }, [selectedTf, dispStr]);

  useEffect(() => {
    const fetchAllData = async () => {
      if (!selectedSymbol || !activeTfsSignature || !descStats) return;
      setIsLoading(true);
      setError(null);
      
      try {
        const activeTfs = activeTfsSignature.split(',').filter(Boolean);
        const results = {};

        await Promise.all(activeTfs.map(async (tf) => {
          const stats = descStats[tf];
          if (!stats) return;
          const startStr = stats.start_date.replace(' ', 'T') + ':00Z';
          const endStr = stats.end_date.replace(' ', 'T') + ':00Z';
          const start_time = new Date(startStr).getTime();
          const end_time = new Date(endStr).getTime() + 86400000;

          const req = await fetch('http://localhost:8000/api/data/ohlcv', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ exchange: 'BINANCE', symbol: selectedSymbol, timeframe: tf, start_time, end_time })
          });
          
          if (req.ok) {
            results[tf] = await req.json();
          }
        }));

        setMultiTfData(results);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };
    
    if (!isGlobalLoading && !isVisualsModalOpen) {
      fetchAllData();
    }
  }, [selectedSymbol, activeTfsSignature, descStats, isGlobalLoading, isVisualsModalOpen]);

  const buildPlotlyConfig = () => {
    const mainData = multiTfData[selectedTf];
    if (!mainData) return { traces: [], layout: {} };

    const traces = [];
    const mainTimeArray = mainData.open_time.map(t => new Date(t).toISOString());

    traces.push({
      x: mainTimeArray, open: mainData.open, high: mainData.high, low: mainData.low, close: mainData.close,
      type: 'candlestick', name: `${selectedSymbol} ${selectedTf}`, yaxis: 'y',
      increasing: { line: { color: '#2ecc71', width: 1.5 }, fillcolor: '#2ecc71' },
      decreasing: { line: { color: '#e74c3c', width: 1.5 }, fillcolor: '#e74c3c' }
    });

    const subchartInds = new Set();

    Object.entries(displayedIndicators).forEach(([indName, indData]) => {
      Object.entries(indData).forEach(([tf, tfData]) => {
        Object.entries(tfData).forEach(([outCol, config]) => {
          const df = multiTfData[tf];
          if (!df || !df[outCol]) return;

          const xTimes = df.open_time.map(t => new Date(t).toISOString());
          const yData = df[outCol];

          if (config.position === 'overlay') {
            traces.push({
              x: xTimes, y: yData, type: config.type === 'bar' ? 'bar' : 'scatter', mode: config.type === 'bar' ? undefined : config.type,
              name: `${outCol} (${tf})`, yaxis: 'y',
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
    const baseHeight = 400;
    const subchartHeight = 150;
    const totalHeight = baseHeight + (subchartsList.length * subchartHeight);

    const layoutYAxes = {};
    const yDomainPadding = 0.02;
    let currentBottom = 0;

    subchartsList.forEach((indTfKey, index) => {
      const axisName = `yaxis${index + 2}`;
      const heightRatio = subchartHeight / totalHeight;
      
      layoutYAxes[axisName] = {
        domain: [currentBottom, currentBottom + heightRatio - yDomainPadding],
        gridcolor: '#30363d', zerolinecolor: '#30363d', tickfont: { color: '#8b949e', size: 10 }
      };

      const [indName, tf] = indTfKey.split('_');
      const tfData = displayedIndicators[indName]?.[tf] || {};

      Object.entries(tfData).forEach(([outCol, config]) => {
        if (config.position !== 'subchart') return;
        const df = multiTfData[tf];
        if (!df || !df[outCol]) return;

        traces.push({
          x: df.open_time.map(t => new Date(t).toISOString()), y: df[outCol],
          type: config.type === 'bar' ? 'bar' : 'scatter', mode: config.type === 'bar' ? undefined : config.type,
          name: `${outCol} (${tf})`, yaxis: `y${index + 2}`,
          line: config.type === 'lines' ? { color: config.color, width: config.width } : undefined,
          marker: config.type !== 'lines' ? { color: config.color } : undefined,
          opacity: config.opacity
        });
      });
      currentBottom += heightRatio;
    });

    layoutYAxes['yaxis'] = {
      domain: [currentBottom, 1],
      gridcolor: '#30363d', zerolinecolor: '#30363d', tickfont: { color: '#8b949e', size: 10 }, side: 'right'
    };

    const layout = {
      height: totalHeight, margin: { l: 50, r: 50, t: 20, b: 40 },
      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', showlegend: true,
      legend: { orientation: 'h', y: 1.05, font: { color: '#c9d1d9' } },
      xaxis: { rangeslider: { visible: false }, gridcolor: '#30363d', zerolinecolor: '#30363d', tickfont: { color: '#8b949e', size: 10 }, type: 'date' },
      ...layoutYAxes,
      hovermode: 'x unified'
    };

    return { traces, layout };
  };

  const { traces, layout } = buildPlotlyConfig();

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm space-y-4 flex flex-col min-h-[600px]">
      <IndicatorVisualsModal 
        isOpen={isVisualsModalOpen} 
        onClose={() => setIsVisualsModalOpen(false)} 
        selectedSymbol={selectedSymbol} 
        availableTfs={availableTfs}
      />

      <div className="flex justify-between items-center border-b border-[#30363d] pb-3">
         <h4 className="text-white text-xs font-bold uppercase tracking-wider flex items-center text-[#58a6ff]">
            <i className="fa-solid fa-chart-candlestick mr-2"></i> Graphique OHLCV Interactif
         </h4>
         
         <div className="flex items-center space-x-3">
            <button 
              onClick={() => setIsVisualsModalOpen(true)}
              className="px-4 py-1.5 bg-[#0d1117] border border-[#58a6ff] hover:bg-[#1f6feb]/20 text-[#58a6ff] hover:text-white text-[11px] font-bold uppercase rounded-lg transition-colors shadow-sm"
            >
              <i className="fa-solid fa-palette mr-2"></i> INDICATEURS
            </button>
            <div className="flex items-center space-x-3 bg-[#0d1117] border border-[#30363d] rounded-lg px-3 py-1.5">
              <span className="text-[11px] text-[#8b949e] font-semibold uppercase tracking-wider">Affichage :</span>
              <select
                value={selectedTf}
                onChange={(e) => setSelectedTf(e.target.value)}
                className="bg-transparent text-xs text-white focus:outline-none font-mono cursor-pointer font-bold"
              >
                {availableTfs.map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </div>
         </div>
      </div>

      <div className="flex-1 w-full bg-[#0d1117] rounded-lg border border-[#30363d] flex items-center justify-center overflow-hidden shadow-inner">
        {isLoading || isGlobalLoading ? (
           <div className="text-[#8b949e] flex flex-col items-center py-20">
             <i className="fa-solid fa-circle-notch fa-spin fa-2x mb-3 text-[#1f6feb]"></i> 
             <span className="text-xs font-mono">Chargement du Graphique Multi-TF...</span>
           </div>
        ) : error ? (
           <div className="text-[#f85149] text-xs font-mono bg-[#f85149]/10 p-4 rounded border border-[#f85149]/20">
             <i className="fa-solid fa-triangle-exclamation mr-2"></i> {error}
           </div>
        ) : traces.length > 0 ? (
           <Plot
              data={traces}
              layout={layout}
              useResizeHandler={true}
              style={{ width: '100%', height: '100%' }}
              config={{ responsive: true, displayModeBar: true, scrollZoom: true }}
           />
        ) : (
           <div className="text-[#8b949e] text-xs italic py-20">
             Aucune donnée à afficher.
           </div>
        )}
      </div>
    </div>
  );
};

export default function ChartingView() {
   const localPairs = useAppStore(state => state.localPairs);
   const descStats = useAppStore(state => state.descStats);
   const fetchStats = useAppStore(state => state.fetchStats);
   
   const [selectedSymbol, setSelectedSymbol] = useState('');

   const currentPair = localPairs.find(p => p.symbol === selectedSymbol);
   const availableTfs = currentPair ? currentPair.timeframe.split(',').map(s => s.trim()) : [];

   useEffect(() => {
     if (!selectedSymbol && localPairs.length > 0) {
       setSelectedSymbol(localPairs[0].symbol);
     }
   }, [localPairs, selectedSymbol]);

   useEffect(() => {
     if (selectedSymbol) {
       fetchStats(selectedSymbol);
     }
   }, [selectedSymbol, fetchStats]);

   return (
     <div className="p-6 space-y-6">
        <SymbolSelector 
           localPairs={localPairs} 
           selectedSymbol={selectedSymbol} 
           onSelect={setSelectedSymbol} 
        />
        
        {selectedSymbol && currentPair && (
           <>
             <ResamplePanel 
                availableTfs={availableTfs} 
                selectedSymbol={selectedSymbol} 
             />
             
             <IndicatorManager selectedSymbol={selectedSymbol} />
             
             <OhlcvChart 
                availableTfs={availableTfs} 
                descStats={descStats} 
                selectedSymbol={selectedSymbol} 
             />
           </>
        )}
     </div>
   );
}