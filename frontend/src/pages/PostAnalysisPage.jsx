// frontend/src/pages/PostAnalysisPage.jsx
import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import { useOptunaStore } from '../entities/optuna/store';

export const PostAnalysisPage = () => {
  const fetchStudies = useOptunaStore((state) => state.fetchStudies);
  const studies = useOptunaStore((state) => state.studies);
  const selectedStudy = useOptunaStore((state) => state.selectedStudy);
  const selectedTrial = useOptunaStore((state) => state.selectedTrial);
  const fetchStudyDetails = useOptunaStore((state) => state.fetchStudyDetails);
  const deleteStudy = useOptunaStore((state) => state.deleteStudy);
  const selectTrial = useOptunaStore((state) => state.selectTrial);
  const isLoadingDetails = useOptunaStore((state) => state.isLoadingDetails);
  const detailsError = useOptunaStore((state) => state.detailsError);
  const featureSymbols = useOptunaStore((state) => state.featureSymbols);
  const fetchFeatureSymbols = useOptunaStore((state) => state.fetchFeatureSymbols);
  const deleteFeatureSymbol = useOptunaStore((state) => state.deleteFeatureSymbol);

  const [activeStudyId, setActiveStudyId] = useState('');

  useEffect(() => {
    fetchStudies();
    fetchFeatureSymbols();
  }, [fetchStudies, fetchFeatureSymbols]);

  const handleStudyChange = (e) => {
    const val = e.target.value;
    setActiveStudyId(val);
    if (val) {
      fetchStudyDetails(val);
    }
  };

  const handleDelete = () => {
    if (!activeStudyId) return;
    if (window.confirm("Êtes-vous sûr de vouloir supprimer cette étude et tous ses résultats ?")) {
      deleteStudy(activeStudyId);
      setActiveStudyId('');
    }
  };

  const handleDeleteFeatureSymbol = async (symbol) => {
    if (window.confirm(`Voulez-vous vraiment supprimer toutes les features calculées pour ${symbol} ? Cette action videra les fichiers HDF5 associés.`)) {
      try {
        await deleteFeatureSymbol(symbol);
      } catch (err) {
        console.error(err);
      }
    }
  };

  // 1. Prepare Pareto Front Plot Data
  const completeTrials = selectedStudy?.trials?.filter(t => t.state === 'COMPLETE') || [];
  const paretoNumbers = selectedStudy?.pareto_front || [];
  
  // Non-Pareto trials
  const nonParetoTrials = completeTrials.filter(t => !paretoNumbers.includes(t.trial_number));
  // Pareto trials
  const paretoTrials = completeTrials.filter(t => paretoNumbers.includes(t.trial_number));

  const scatterTraceNonPareto = {
    x: nonParetoTrials.map(t => t.values[1] * 100.0), // MaxDD in %
    y: nonParetoTrials.map(t => t.values[0]), // Sharpe/Sortino
    text: nonParetoTrials.map(t => `Trial ${t.trial_number}<br>IS: ${t.params.is_length_days}d | OOS: ${t.params.oos_length_hours}h`),
    mode: 'markers',
    type: 'scatter',
    name: 'Trials Normaux',
    marker: {
      color: '#1f6feb',
      size: 8,
      opacity: 0.6,
      line: {
        color: '#30363d',
        width: 1
      }
    },
    hoverinfo: 'text+x+y'
  };

  const scatterTracePareto = {
    x: paretoTrials.map(t => t.values[1] * 100.0), // MaxDD in %
    y: paretoTrials.map(t => t.values[0]), // Sharpe/Sortino
    text: paretoTrials.map(t => `Trial ${t.trial_number} (Pareto)<br>IS: ${t.params.is_length_days}d | OOS: ${t.params.oos_length_hours}h`),
    mode: 'markers',
    type: 'scatter',
    name: 'Front de Pareto',
    marker: {
      color: '#3fb950',
      symbol: 'diamond',
      size: 12,
      line: {
        color: '#ffffff',
        width: 1.5
      }
    },
    hoverinfo: 'text+x+y'
  };

  // If a trial is selected, we highlight it
  const selectedTrace = selectedTrial ? {
    x: [selectedTrial.values[1] * 100.0],
    y: [selectedTrial.values[0]],
    mode: 'markers',
    type: 'scatter',
    name: `Sélectionné (${selectedTrial.trial_number})`,
    marker: {
      color: '#f9826c',
      symbol: 'circle',
      size: 16,
      line: {
        color: '#ffffff',
        width: 2
      }
    },
    hoverinfo: 'none'
  } : null;

  const paretoLayout = {
    title: {
      text: `Front de Pareto - Espace Multi-Objectif`,
      font: { color: '#c9d1d9', size: 14 }
    },
    xaxis: {
      title: 'Maximum Drawdown OOS (%)',
      titlefont: { color: '#8b949e', size: 11 },
      tickfont: { color: '#8b949e' },
      gridcolor: '#21262d',
      zerolinecolor: '#30363d',
      autorange: 'reversed' // Reversed because lower Drawdown is better
    },
    yaxis: {
      title: `${selectedStudy?.config?.metric_type === 'sortino' ? 'Sortino' : 'Sharpe'} OOS`,
      titlefont: { color: '#8b949e', size: 11 },
      tickfont: { color: '#8b949e' },
      gridcolor: '#21262d',
      zerolinecolor: '#30363d'
    },
    paper_bgcolor: '#161b22',
    plot_bgcolor: '#161b22',
    margin: { l: 50, r: 20, t: 40, b: 50 },
    showlegend: true,
    legend: {
      font: { color: '#c9d1d9', size: 10 },
      orientation: 'h',
      x: 0,
      y: -0.2
    },
    height: 350
  };

  // 2. Prepare OOS Equity Curve Plot Data
  const equityTrace = selectedTrial ? {
    x: selectedTrial.timestamps ? selectedTrial.timestamps.map(t => new Date(t)) : [],
    y: selectedTrial.equity_curve || [],
    type: 'scatter',
    mode: 'lines',
    name: `Trial ${selectedTrial.trial_number} OOS`,
    line: {
      color: '#58a6ff',
      width: 2
    },
    fill: 'tozeroy',
    fillcolor: 'rgba(88, 166, 255, 0.05)'
  } : null;

  const equityLayout = {
    title: {
      text: selectedTrial ? `Courbe d'Équité OOS Stitched - Trial ${selectedTrial.trial_number}` : 'Courbe d\'Équité OOS',
      font: { color: '#c9d1d9', size: 14 }
    },
    xaxis: {
      tickfont: { color: '#8b949e' },
      gridcolor: '#21262d',
      zerolinecolor: '#30363d'
    },
    yaxis: {
      title: 'Multiplicateur Capital',
      titlefont: { color: '#8b949e', size: 11 },
      tickfont: { color: '#8b949e' },
      gridcolor: '#21262d',
      zerolinecolor: '#30363d'
    },
    paper_bgcolor: '#161b22',
    plot_bgcolor: '#161b22',
    margin: { l: 50, r: 20, t: 40, b: 40 },
    height: 350
  };

  const handlePlotClick = (event) => {
    if (!event.points || event.points.length === 0) return;
    const pt = event.points[0];
    // Find trial number by matching coordinates
    const clickedTrial = completeTrials.find(t => 
      Math.abs(t.values[1] * 100.0 - pt.x) < 1e-4 && 
      Math.abs(t.values[0] - pt.y) < 1e-4
    );
    if (clickedTrial) {
      selectTrial(clickedTrial);
    }
  };

  return (
    <div className="p-6">
      {/* Grid of Optimization Studies Cards */}
      <h3 className="text-white text-base font-bold mb-4 flex items-center">
        <span className="text-[#58a6ff] mr-2">📂</span>
        Charger une Étude Optuna
      </h3>
      
      {studies.length === 0 ? (
        <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 text-center text-gray-500 text-sm italic mb-6">
          Aucun run d'optimisation enregistré pour le moment.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          {studies.map((s) => {
            const isSelected = activeStudyId === s.study_id;
            return (
              <div
                key={s.study_id}
                onClick={() => {
                  setActiveStudyId(s.study_id);
                  fetchStudyDetails(s.study_id);
                }}
                className={`bg-[#161b22] border rounded-xl p-4 cursor-pointer transition-all flex flex-col justify-between hover:border-[#8b949e] ${
                  isSelected ? 'border-[#1f6feb] ring-1 ring-[#1f6feb] bg-[#1f6feb]/5' : 'border-[#30363d]'
                }`}
              >
                <div>
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-white font-bold text-sm font-mono">
                      {s.config?.symbol || "Unknown"} ({s.config?.timeframe || "N/A"})
                    </span>
                    <span className="text-[10px] text-gray-500 font-mono">
                      {s.created_at ? s.created_at.substring(0, 16).replace('T', ' ') : 'N/A'}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-[11px] text-gray-400 mb-3 font-mono">
                    <div>
                      <span className="text-gray-500 block uppercase text-[9px]">Métrique</span>
                      {s.config?.metric_type || "N/A"}
                    </div>
                    <div>
                      <span className="text-gray-500 block uppercase text-[9px]">Cible</span>
                      {s.config?.target_threshold}% wick
                    </div>
                    <div>
                      <span className="text-gray-500 block uppercase text-[9px]">Essais</span>
                      {s.trials_count || 0} Complete
                    </div>
                    <div>
                      <span className="text-gray-500 block uppercase text-[9px]">Algorithme</span>
                      {s.config?.model_type || "N/A"}
                    </div>
                  </div>
                </div>

                <div className="flex justify-between items-center mt-2 pt-2 border-t border-[#30363d] gap-2">
                  <span className={`text-[10px] uppercase font-bold ${
                    isSelected ? 'text-[#58a6ff]' : 'text-gray-500'
                  }`}>
                    {isSelected ? '✓ Sélectionné' : 'Charger'}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm("Voulez-vous vraiment supprimer cette étude et tous ses résultats ?")) {
                        deleteStudy(s.study_id);
                        if (isSelected) {
                          setActiveStudyId('');
                        }
                      }
                    }}
                    className="text-gray-500 hover:text-red-500 p-1 text-xs transition-colors"
                    title="Supprimer cette étude"
                  >
                    <i className="fa-solid fa-trash-can"></i>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {isLoadingDetails ? (
        <div className="text-[#8b949e] flex flex-col items-center justify-center py-40 bg-[#161b22] rounded-xl border border-[#30363d]">
          <i className="fa-solid fa-circle-notch fa-spin fa-3x mb-4 text-[#1f6feb]"></i>
          <span className="font-mono text-sm">Chargement des données de l'optimisation...</span>
        </div>
      ) : detailsError ? (
        <div className="bg-red-950/20 border border-red-900 rounded-xl p-6 text-sm text-red-400">
          <i className="fa-solid fa-circle-exclamation mr-2"></i>
          Une erreur est survenue : {detailsError}
        </div>
      ) : !selectedStudy ? (
        <div className="flex flex-col items-center justify-center py-40 text-gray-500 text-sm italic bg-[#161b22] border border-[#30363d] rounded-xl">
          <i className="fa-solid fa-arrow-up text-3xl mb-4 text-[#30363d]"></i>
          Veuillez sélectionner une étude Optuna dans le menu déroulant ci-dessus.
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
          
          {/* Left Column: Pareto Front plot & trial checklist */}
          <div className="xl:col-span-6 flex flex-col space-y-6">
            
            {/* Pareto front plot */}
            <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-4 shadow-sm overflow-hidden">
              <Plot
                data={selectedTrace ? [scatterTraceNonPareto, scatterTracePareto, selectedTrace] : [scatterTraceNonPareto, scatterTracePareto]}
                layout={paretoLayout}
                useResizeHandler={true}
                style={{ width: '100%' }}
                config={{ responsive: true, displayModeBar: false }}
                onClick={handlePlotClick}
              />
              <p className="text-[10px] text-gray-500 italic text-center mt-2">
                * Cliquez sur un point du graphique pour sélectionner et analyser la courbe d'équité de ce trial.
              </p>
            </div>

            {/* Trials table */}
            <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm flex-1 flex flex-col min-h-[350px]">
              <h4 className="text-white text-sm font-bold uppercase tracking-wider mb-3 flex items-center">
                <i className="fa-solid fa-list-check text-[#58a6ff] mr-2"></i> Liste de Tous les Essais
              </h4>
              <div className="flex-1 overflow-y-auto max-h-[350px] border border-[#30363d] rounded-lg">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-[#0d1117] text-[#8b949e] border-b border-[#30363d] uppercase tracking-wider text-[10px]">
                      <th className="p-3 text-center">#</th>
                      <th className="p-3 text-center">Pareto</th>
                      <th className="p-3">IS / OOS</th>
                      <th className="p-3 text-right">Métrique OOS</th>
                      <th className="p-3 text-right">MaxDD OOS</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#30363d]">
                    {completeTrials.map((trial) => {
                      const isPareto = paretoNumbers.includes(trial.trial_number);
                      const isSelected = selectedTrial?.trial_number === trial.trial_number;
                      return (
                        <tr
                          key={trial.trial_number}
                          onClick={() => selectTrial(trial)}
                          className={`hover:bg-[#1f6feb]/5 font-mono cursor-pointer transition-colors ${
                            isSelected 
                              ? 'bg-[#1f6feb]/15 text-white border-l-2 border-[#1f6feb]' 
                              : isPareto 
                                ? 'bg-[#238636]/5 text-gray-200' 
                                : 'text-gray-400'
                          }`}
                        >
                          <td className="p-3 text-center text-gray-500 font-semibold">{trial.trial_number}</td>
                          <td className="p-3 text-center">
                            {isPareto ? (
                              <i className="fa-solid fa-crown text-yellow-500" title="Front de Pareto"></i>
                            ) : (
                              <span>-</span>
                            )}
                          </td>
                          <td className="p-3">
                            {trial.params.is_length_days}d / {trial.params.oos_length_hours}h
                          </td>
                          <td className={`p-3 text-right font-bold ${
                            trial.values[0] > 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                          }`}>
                            {trial.values[0].toFixed(3)}
                          </td>
                          <td className="p-3 text-right text-orange-400">
                            {(trial.values[1] * 100.0).toFixed(2)}%
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

          </div>

          {/* Right Column: Equity curve and Trial metrics */}
          <div className="xl:col-span-6 flex flex-col space-y-6">
            
            {/* Detailed metrics for the selected trial */}
            {selectedTrial ? (
              <>
                {/* Metrics cards */}
                <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
                  <div className="flex justify-between items-center border-b border-[#30363d] pb-3 mb-4">
                    <h3 className="text-white text-base font-bold flex items-center">
                      <span className="text-[#58a6ff] mr-2">🎯</span>
                      Analyse : Trial #{selectedTrial.trial_number}
                      {paretoNumbers.includes(selectedTrial.trial_number) && (
                        <span className="text-xs bg-yellow-500/10 text-yellow-500 border border-yellow-500/20 px-2 py-0.5 rounded ml-3 uppercase font-bold">
                          Pareto Optimal
                        </span>
                      )}
                    </h3>
                    <span className="text-xs font-mono text-gray-400">
                      Modèle : {selectedStudy.config.model_type.toUpperCase()}
                    </span>
                  </div>

                  {/* Top row: Results */}
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[#8b949e] block text-[10px] uppercase font-semibold">PnL Net</span>
                      <span className={`text-base font-mono font-bold ${
                        selectedTrial.metrics.final_equity >= 100.0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                      }`}>
                        {(selectedTrial.metrics.final_equity - 100.0).toFixed(2)}%
                      </span>
                    </div>
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[#8b949e] block text-[10px] uppercase font-semibold">Sharpe OOS</span>
                      <span className="text-white font-mono text-base font-bold">{selectedTrial.metrics.sharpe.toFixed(3)}</span>
                    </div>
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[#8b949e] block text-[10px] uppercase font-semibold">Sortino OOS</span>
                      <span className="text-white font-mono text-base font-bold">
                        {selectedTrial.metrics.sortino ? (selectedTrial.metrics.sortino === Infinity ? '∞' : selectedTrial.metrics.sortino.toFixed(3)) : 'N/A'}
                      </span>
                    </div>
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[#8b949e] block text-[10px] uppercase font-semibold">Max Drawdown</span>
                      <span className="text-orange-400 font-mono text-base font-bold">{(selectedTrial.metrics.max_drawdown * 100.0).toFixed(2)}%</span>
                    </div>
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[#8b949e] block text-[10px] uppercase font-semibold">Win Rate</span>
                      <span className="text-white font-mono text-base font-bold">{(selectedTrial.metrics.win_rate * 100.0).toFixed(1)}%</span>
                    </div>
                  </div>

                  {/* Parameter summary */}
                  <h4 className="text-xs font-bold uppercase tracking-wider text-[#8b949e] mb-2.5">
                    Hyperparamètres Optimisés
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-xs mb-4">
                    <div>
                      <span className="text-[#8b949e] block">Longueur IS :</span>
                      <strong className="text-white font-mono">{selectedTrial.params.is_length_days} Jours</strong>
                    </div>
                    <div>
                      <span className="text-[#8b949e] block">Longueur OOS :</span>
                      <strong className="text-white font-mono">{selectedTrial.params.oos_length_hours} Heures</strong>
                    </div>
                    <div>
                      <span className="text-[#8b949e] block">Learning Rate :</span>
                      <strong className="text-white font-mono">{selectedTrial.params.learning_rate.toFixed(5)}</strong>
                    </div>
                    <div>
                      <span className="text-[#8b949e] block">Profondeur Max :</span>
                      <strong className="text-white font-mono">{selectedTrial.params.max_depth}</strong>
                    </div>
                    <div>
                      <span className="text-[#8b949e] block">Colsample Bytree :</span>
                      <strong className="text-white font-mono">{selectedTrial.params.colsample_bytree.toFixed(3)}</strong>
                    </div>
                    <div>
                      <span className="text-[#8b949e] block">Total Trades :</span>
                      <strong className="text-white font-mono">{selectedTrial.metrics.trades_count} ({selectedTrial.metrics.wins_count} V / {selectedTrial.metrics.trades_count - selectedTrial.metrics.wins_count} D)</strong>
                    </div>
                  </div>
                  
                  {/* Additional Backtest Configurations & Indicators */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-[#30363d]">
                    <div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-[#8b949e] mb-2">
                        Paramètres de Backtest OOS
                      </h4>
                      <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-xs space-y-1.5">
                        <div className="flex justify-between">
                          <span className="text-gray-400">Paire Active :</span>
                          <span className="text-white font-mono">{selectedStudy.config.symbol}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-400">Timeframe :</span>
                          <span className="text-white font-mono">{selectedStudy.config.timeframe}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-400">Sens Trading :</span>
                          <span className="text-white font-mono uppercase">{selectedStudy.config.trading_direction}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-400">Frais (Ratio) :</span>
                          <span className="text-white font-mono">{selectedStudy.config.fee_rate} ({selectedStudy.config.fee_rate * 100.0}%)</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-400">Slippage (Ratio) :</span>
                          <span className="text-white font-mono">{selectedStudy.config.slippage_rate} ({selectedStudy.config.slippage_rate * 100.0}%)</span>
                        </div>
                      </div>
                    </div>
                    <div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-[#8b949e] mb-2">
                        Indicateurs Utilisés ({selectedStudy.config.feature_cols?.length || 0})
                      </h4>
                      <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 max-h-[110px] overflow-y-auto text-[11px] font-mono text-[#58a6ff] space-y-1">
                        {selectedStudy.config.feature_cols && selectedStudy.config.feature_cols.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {selectedStudy.config.feature_cols.map((feat, idx) => (
                              <span key={idx} className="bg-[#1f6feb]/10 border border-[#1f6feb]/20 px-1.5 py-0.5 rounded text-[10px]">
                                {feat}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-500 italic">Aucun indicateur enregistré</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Equity curve plot */}
                <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-4 shadow-sm overflow-hidden">
                  <Plot
                    data={[equityTrace]}
                    layout={equityLayout}
                    useResizeHandler={true}
                    style={{ width: '100%' }}
                    config={{ responsive: true, displayModeBar: true, scrollZoom: true }}
                  />
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-gray-500 text-sm italic bg-[#161b22] border border-[#30363d] rounded-xl flex-1">
                <i className="fa-solid fa-chart-line text-3xl mb-4 text-[#30363d]"></i>
                Aucun essai sélectionné.
                <p className="text-xs text-gray-500 mt-2 max-w-sm text-center">
                  Veuillez cliquer sur un essai dans la liste ou sur un point du front de Pareto pour visualiser ses performances détaillées et sa courbe d'équité OOS glissante.
                </p>
              </div>
            )}

          </div>

        </div>
      )}

      {/* Local feature engineering data management */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm mt-6">
        <h4 className="text-white text-sm font-bold uppercase tracking-wider mb-4 flex items-center">
          <span className="text-[#58a6ff] mr-2">💾</span>
          Fichiers de Features Générés
        </h4>
        {featureSymbols.length === 0 ? (
          <p className="text-xs text-gray-500 italic">Aucun fichier de features calculé sur la machine hôte.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {featureSymbols.map((sym) => (
              <div 
                key={sym} 
                className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 flex justify-between items-center"
              >
                <div>
                  <span className="text-white font-mono font-bold text-xs block">{sym}</span>
                  <span className="text-[9px] text-gray-500 font-mono">Dossier: optuna_features/{sym}</span>
                </div>
                <button
                  onClick={() => handleDeleteFeatureSymbol(sym)}
                  className="text-gray-500 hover:text-red-500 p-2 transition-colors"
                  title={`Supprimer les features calculées pour ${sym}`}
                >
                  <i className="fa-solid fa-trash-can text-xs"></i>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
