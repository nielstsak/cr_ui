// frontend/src/pages/MLOptunaPage.jsx
import React, { useState, useEffect } from 'react';
import { useMarketStore } from '../entities/market/store';
import { useOptunaStore } from '../entities/optuna/store';
import { useTaskPolling } from '../features/DataIngestion/useTaskPolling';

export const MLOptunaPage = () => {
  const activeSymbol = useMarketStore((state) => state.activeSymbol);
  const setActiveSymbol = useMarketStore((state) => state.setActiveSymbol);
  const localPairs = useMarketStore((state) => state.localPairs);

  const startOptimization = useOptunaStore((state) => state.startOptimization);
  const activeTaskId = useOptunaStore((state) => state.activeTaskId);
  const isOptimizing = useOptunaStore((state) => state.isOptimizing);
  const setOptimizing = useOptunaStore((state) => state.setOptimizing);
  const setTaskId = useOptunaStore((state) => state.setTaskId);
  const fetchStudies = useOptunaStore((state) => state.fetchStudies);

  // Form State
  const [formData, setFormData] = useState({
    target_format: 'classification',
    target_wick_type: 'High-Open',
    target_threshold: 2.0,
    model_type: 'lightgbm',
    metric_type: 'sharpe',
    trading_direction: 'both',
    fee_rate: 0.001,
    slippage_rate: 0.0005,
    entry_sig_threshold: 0.5,
    n_trials: 20,
    is_length_days_min: 15,
    is_length_days_max: 90,
    oos_length_hours_min: 12,
    oos_length_hours_max: 168,
    learning_rate_min: 0.01,
    learning_rate_max: 0.3,
    max_depth_min: 3,
    max_depth_max: 8,
    colsample_bytree_min: 0.3,
    colsample_bytree_max: 1.0
  });

  const [selectedTimeframe, setSelectedTimeframe] = useState('');
  const [isDefaultsLoaded, setIsDefaultsLoaded] = useState(false);

  // Agentic Loop UI States
  const [activeTab, setActiveTab] = useState('manual');
  const [agenticLoopStatus, setAgenticLoopStatus] = useState(null);
  const [openIteration, setOpenIteration] = useState(null);

  // Poll agentic loop status
  useEffect(() => {
    let intervalId;
    const fetchStatus = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/optuna/agentic-loop');
        if (res.ok) {
          const data = await res.json();
          setAgenticLoopStatus(data);
        }
      } catch (e) {
        console.error("Error fetching agentic loop status:", e);
      }
    };

    fetchStatus();
    intervalId = setInterval(fetchStatus, 4000); // poll every 4 seconds

    return () => clearInterval(intervalId);
  }, []);

  // Fetch saved defaults on mount
  useEffect(() => {
    const fetchDefaults = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/optuna/defaults');
        if (response.ok) {
          const data = await response.json();
          if (data && Object.keys(data).length > 0) {
            setFormData(prev => ({
              ...prev,
              ...data
            }));
            console.log("Optuna defaults loaded:", data);
          }
        }
      } catch (e) {
        console.error("Error loading defaults:", e);
      } finally {
        setIsDefaultsLoaded(true);
      }
    };
    fetchDefaults();
  }, []);

  // Update selectedTimeframe when activeSymbol changes
  useEffect(() => {
    if (activeSymbol) {
      const selectedPair = localPairs.find(p => p.symbol === activeSymbol);
      if (selectedPair && selectedPair.timeframe) {
        const tfs = selectedPair.timeframe.split(',').map(t => t.trim());
        setSelectedTimeframe(tfs[0]);
      }
    } else {
      setSelectedTimeframe('');
    }
  }, [activeSymbol, localPairs]);

  // Update entry threshold default when format changes (only after defaults are loaded)
  useEffect(() => {
    if (!isDefaultsLoaded) return;
    if (formData.target_format === 'regression') {
      setFormData(prev => ({ ...prev, entry_sig_threshold: prev.target_threshold }));
    } else {
      setFormData(prev => ({ ...prev, entry_sig_threshold: 0.5 }));
    }
  }, [formData.target_format, formData.target_threshold, isDefaultsLoaded]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    const numericFields = [
      'target_threshold', 'fee_rate', 'slippage_rate', 'entry_sig_threshold',
      'n_trials', 'is_length_days_min', 'is_length_days_max', 'oos_length_hours_min',
      'oos_length_hours_max', 'learning_rate_min', 'learning_rate_max',
      'max_depth_min', 'max_depth_max', 'colsample_bytree_min', 'colsample_bytree_max'
    ];
    
    setFormData(prev => ({
      ...prev,
      [name]: numericFields.includes(name) ? parseFloat(value) : value
    }));
  };

  const handleStart = () => {
    if (!activeSymbol || !selectedTimeframe) return;

    startOptimization({
      symbol: activeSymbol,
      timeframe: selectedTimeframe,
      ...formData
    });
  };

  // Setup task polling
  const { progress, status, error, result } = useTaskPolling(activeTaskId, {
    onComplete: () => {
      setOptimizing(false);
      setTaskId(null);
      fetchStudies();
    },
    onFailure: (err) => {
      setOptimizing(false);
      setTaskId(null);
    }
  });

  const activePair = localPairs.find(p => p.symbol === activeSymbol);
  const trials = result?.trials || [];
  const paretoFront = result?.pareto_front || [];

  return (
    <div className="p-6">
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        
        {/* Left Column: Form Parameters */}
        <div className="xl:col-span-5 flex flex-col space-y-6">
          <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
            <h3 className="text-[#58a6ff] text-sm font-bold uppercase tracking-wider mb-4 flex items-center">
              <i className="fa-solid fa-brain mr-2.5"></i> Configuration ML & Optuna
            </h3>

            <div className="space-y-4">
              {/* Symbol selector */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
                    Paire active
                  </label>
                  <select
                    value={activeSymbol}
                    onChange={(e) => setActiveSymbol(e.target.value)}
                    disabled={isOptimizing}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg p-2.5 text-sm font-mono text-white focus:outline-none focus:border-[#1f6feb]"
                  >
                    <option value="">-- Sélectionner une paire --</option>
                    {localPairs.map((p) => (
                      <option key={p.symbol} value={p.symbol}>
                        {p.symbol}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
                    Timeframe
                  </label>
                  <select
                    value={selectedTimeframe}
                    onChange={(e) => setSelectedTimeframe(e.target.value)}
                    disabled={isOptimizing || !activeSymbol}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg p-2.5 text-sm font-mono text-white focus:outline-none focus:border-[#1f6feb]"
                  >
                    {!activeSymbol && <option value="">-- Aucun --</option>}
                    {activeSymbol && localPairs.find(p => p.symbol === activeSymbol)?.timeframe.split(',').map(t => t.trim()).map(t => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* AI Optimized Parameters Summary Box */}
              <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3.5 space-y-2 text-xs text-[#8b949e]">
                <h4 className="text-[#58a6ff] font-bold uppercase mb-1.5 flex items-center">
                  <i className="fa-solid fa-wand-magic-sparkles mr-2 text-yellow-500"></i>
                  Optimisé par Optuna :
                </h4>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <div>• <strong>Format :</strong> Classif (Triple Barrier)</div>
                  <div>• <strong>Algorithme :</strong> LightGBM / XGBoost</div>
                  <div>• <strong>Seuil Cible :</strong> 0.3% à 2.5%</div>
                  <div>• <strong>Signal Entrée :</strong> Dynamique</div>
                  <div>• <strong>Horizon :</strong> 2 à 24 bougies</div>
                  <div>• <strong>Indicateurs :</strong> Multi-TF (Sans CDL)</div>
                  <div>• <strong>Nombre Feat :</strong> Top 5 à 50</div>
                  <div>• <strong>Objectif :</strong> Sortino Ratio</div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
                    Frais (Ratio)
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    name="fee_rate"
                    value={formData.fee_rate}
                    onChange={handleChange}
                    disabled={isOptimizing}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg p-2 text-xs font-mono text-white focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
                    Slippage (Ratio)
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    name="slippage_rate"
                    value={formData.slippage_rate}
                    onChange={handleChange}
                    disabled={isOptimizing}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg p-2 text-xs font-mono text-white focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-[#8b949e] mb-1.5">
                    Trials Optuna
                  </label>
                  <input
                    type="number"
                    name="n_trials"
                    value={formData.n_trials}
                    onChange={handleChange}
                    disabled={isOptimizing}
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg p-2 text-xs font-mono text-white focus:outline-none"
                  />
                </div>
              </div>

              <hr className="border-[#30363d] my-3" />

              {/* Espace de Recherche / Bornes */}
              <h4 className="text-xs font-bold uppercase tracking-wider text-[#8b949e] mb-2 flex items-center">
                <i className="fa-solid fa-sliders mr-2"></i> Bornes Espace de Recherche
              </h4>

              <div className="space-y-3 bg-[#0d1117] border border-[#30363d] rounded-lg p-3">
                {/* IS Day range */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Longueur IS Min (Jours)</label>
                    <input
                      type="number"
                      name="is_length_days_min"
                      value={formData.is_length_days_min}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Longueur IS Max (Jours)</label>
                    <input
                      type="number"
                      name="is_length_days_max"
                      value={formData.is_length_days_max}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                </div>

                {/* OOS Hours range */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Longueur OOS Min (Heures)</label>
                    <input
                      type="number"
                      name="oos_length_hours_min"
                      value={formData.oos_length_hours_min}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Longueur OOS Max (Heures)</label>
                    <input
                      type="number"
                      name="oos_length_hours_max"
                      value={formData.oos_length_hours_max}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                </div>

                {/* Learning rate / Depth / Colsample */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Learning Rate Min</label>
                    <input
                      type="number"
                      step="0.01"
                      name="learning_rate_min"
                      value={formData.learning_rate_min}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Learning Rate Max</label>
                    <input
                      type="number"
                      step="0.01"
                      name="learning_rate_max"
                      value={formData.learning_rate_max}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Profondeur Max Min</label>
                    <input
                      type="number"
                      name="max_depth_min"
                      value={formData.max_depth_min}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Profondeur Max Max</label>
                    <input
                      type="number"
                      name="max_depth_max"
                      value={formData.max_depth_max}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Colsample Min</label>
                    <input
                      type="number"
                      step="0.05"
                      name="colsample_bytree_min"
                      value={formData.colsample_bytree_min}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-[#8b949e] mb-1">Colsample Max</label>
                    <input
                      type="number"
                      step="0.05"
                      name="colsample_bytree_max"
                      value={formData.colsample_bytree_max}
                      onChange={handleChange}
                      disabled={isOptimizing}
                      className="w-full bg-[#161b22] border border-[#30363d] rounded p-1.5 text-xs font-mono text-white focus:outline-none"
                    />
                  </div>
                </div>
              </div>

              {/* Action Button */}
              <button
                onClick={handleStart}
                disabled={isOptimizing || !activeSymbol}
                className={`w-full py-3 rounded-lg text-sm font-bold uppercase tracking-wider transition-colors flex items-center justify-center ${
                  isOptimizing || !activeSymbol
                    ? 'bg-[#21262d] text-gray-500 cursor-not-allowed border border-[#30363d]'
                    : 'bg-[#238636] hover:bg-[#2ea043] text-white'
                }`}
              >
                {isOptimizing ? (
                  <>
                    <i className="fa-solid fa-circle-notch fa-spin mr-2"></i>
                    Optimisation en cours...
                  </>
                ) : (
                  <>
                    <i className="fa-solid fa-bolt mr-2"></i>
                    Lancer l'optimisation
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Progress Section */}
          {isOptimizing && (
            <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
              <h3 className="text-white text-sm font-bold mb-3 flex items-center">
                <i className="fa-solid fa-spinner fa-spin mr-2 text-[#58a6ff]"></i>
                Progression Générale
              </h3>
              
              <div className="w-full bg-[#0d1117] rounded-full h-3 border border-[#30363d] overflow-hidden mb-2">
                <div 
                  className="bg-[#1f6feb] h-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
              
              <div className="flex justify-between text-xs font-mono text-gray-400">
                <span>Statut : {status}</span>
                <span>{progress.toFixed(1)}%</span>
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-950/20 border border-red-900 rounded-xl p-4 text-sm text-red-400 flex items-start space-x-2.5">
              <i className="fa-solid fa-circle-exclamation mt-0.5"></i>
              <div>
                <p className="font-bold">Erreur d'optimisation</p>
                <p className="text-xs text-gray-400 mt-1">{error}</p>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Live Trials / Pareto Front / Agentic loop */}
        <div className="xl:col-span-7 flex flex-col">
          <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 shadow-sm flex-1 flex flex-col min-h-[450px]">
            <div className="flex border-b border-[#30363d] pb-2 mb-4 justify-between items-center">
              <div className="flex space-x-4">
                <button
                  onClick={() => setActiveTab('manual')}
                  className={`text-sm font-bold uppercase tracking-wider pb-2 border-b-2 transition-colors ${
                    activeTab === 'manual'
                      ? 'border-[#58a6ff] text-[#58a6ff]'
                      : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <i className="fa-solid fa-chart-line mr-2"></i> Étude Manuelle
                </button>
                <button
                  onClick={() => setActiveTab('agentic')}
                  className={`text-sm font-bold uppercase tracking-wider pb-2 border-b-2 transition-colors ${
                    activeTab === 'agentic'
                      ? 'border-[#58a6ff] text-[#58a6ff]'
                      : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <i className="fa-solid fa-robot mr-2"></i> Optimisation Agentic
                </button>
              </div>
              {activeTab === 'manual' && activeSymbol && (
                <span className="text-xs text-gray-400 font-mono">Paire active : {activeSymbol}</span>
              )}
            </div>

            {activeTab === 'manual' ? (
              (!isOptimizing && trials.length === 0 ? (
                <div className="flex flex-col items-center justify-center flex-1 py-10 text-gray-500 text-sm italic text-center px-6">
                  <i className="fa-solid fa-diagram-project text-3xl mb-3 text-[#30363d]"></i>
                  Aucune optimisation active.
                  <p className="text-xs text-gray-500 mt-2 max-w-md">
                    Réglez vos paramètres à gauche puis cliquez sur "Lancer l'optimisation". Les résultats des trials s'afficheront en temps réel.
                  </p>
                </div>
              ) : (
                <div className="flex-1 flex flex-col min-h-0">
                  <div className="flex justify-between items-center mb-3">
                    <span className="text-sm text-gray-400">
                      Nombre total de trials calculés : <strong className="text-white font-mono">{trials.length}</strong>
                    </span>
                    <span className="text-xs bg-[#1f6feb]/10 text-[#58a6ff] px-2.5 py-1 rounded border border-[#1f6feb]/20 flex items-center font-semibold">
                      <i className="fa-solid fa-crown mr-1.5 text-yellow-500 animate-pulse"></i>
                      Pareto : {paretoFront.length} trial(s)
                    </span>
                  </div>

                  <div className="flex-1 overflow-y-auto max-h-[600px] border border-[#30363d] rounded-lg">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-[#0d1117] text-[#8b949e] border-b border-[#30363d] uppercase tracking-wider text-[10px]">
                          <th className="p-3 font-semibold text-center w-12">#</th>
                          <th className="p-3 font-semibold text-center">Pareto</th>
                          <th className="p-3 font-semibold">IS/OOS</th>
                          <th className="p-3 font-semibold">Alg/Fmt</th>
                          <th className="p-3 font-semibold">Cible/Entrée</th>
                          <th className="p-3 font-semibold text-center">Horizon</th>
                          <th className="p-3 font-semibold text-center">Feat</th>
                          <th className="p-3 font-semibold text-right">Metric OOS</th>
                          <th className="p-3 font-semibold text-right">MaxDD OOS</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#30363d]">
                        {trials.slice().reverse().map((trial) => {
                          const isPareto = paretoFront.includes(trial.trial_number);
                          const optModel = trial.params.model_type || 'lgb';
                          const optFormat = trial.params.target_format === 'classification' ? 'Class' : 'Reg';
                          const optThreshold = trial.params.target_threshold ? `${trial.params.target_threshold.toFixed(2)}%` : '-';
                          const optEntry = trial.params.entry_sig_threshold ? trial.params.entry_sig_threshold.toFixed(2) : '-';
                          const optHold = trial.params.hold_candles || 1;
                          const optFeatures = trial.params.top_n_features || 35;
                          const optMetric = trial.params.metric_type || 'pnl';
                          
                          return (
                            <tr 
                              key={trial.trial_number} 
                              className={`hover:bg-[#161b22] font-mono transition-colors ${
                                isPareto ? 'bg-[#238636]/10 text-white' : 'text-gray-300'
                              }`}
                            >
                              <td className="p-3 text-center text-gray-500 font-semibold">{trial.trial_number}</td>
                              <td className="p-3 text-center">
                                {isPareto ? (
                                  <i className="fa-solid fa-crown text-yellow-500 text-sm" title="Sur le front de Pareto"></i>
                                ) : (
                                  <span className="text-gray-600">-</span>
                                )}
                              </td>
                              <td className="p-3">
                                {trial.params.is_length_days}d/{trial.params.oos_length_hours}h
                              </td>
                              <td className="p-3 text-gray-400">
                                {optModel.substring(0,3)}/{optFormat}
                              </td>
                              <td className="p-3 text-gray-400">
                                {optThreshold}/{optEntry}
                              </td>
                              <td className="p-3 text-center">
                                {optHold}c
                              </td>
                              <td className="p-3 text-center text-gray-400">
                                {optFeatures}
                              </td>
                              <td className={`p-3 text-right font-bold ${
                                trial.values[0] > 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                              }`}>
                                {trial.values[0].toFixed(2)} <span className="text-[10px] text-gray-500">({optMetric})</span>
                              </td>
                              <td className="p-3 text-right text-orange-400 font-semibold">
                                {(trial.values[1] * 100.0).toFixed(2)}%
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))
            ) : (
              (!agenticLoopStatus || !agenticLoopStatus.history || agenticLoopStatus.history.length === 0) && agenticLoopStatus?.status !== 'running' ? (
                <div className="flex flex-col items-center justify-center flex-1 py-10 text-gray-500 text-sm italic text-center px-6">
                  <i className="fa-solid fa-robot text-3xl mb-3 text-[#30363d]"></i>
                  Aucun processus d'optimisation automatique en cours.
                  <p className="text-xs text-gray-500 mt-2 max-w-md">
                    Lancez la boucle d'optimisation depuis le terminal (`python agentic_optimization_loop.py`) pour suivre la progression automatique et l'historique des itérations ici.
                  </p>
                </div>
              ) : (
                <div className="flex-1 flex flex-col min-h-0 space-y-4">
                  {/* Status Card */}
                  <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-4 flex flex-col space-y-3">
                    <div className="flex justify-between items-center">
                      <div className="flex items-center space-x-2">
                        {agenticLoopStatus.status === 'running' ? (
                          <>
                            <span className="w-2.5 h-2.5 bg-[#3fb950] rounded-full animate-ping"></span>
                            <span className="text-xs text-[#3fb950] font-bold uppercase tracking-wider">Boucle en cours...</span>
                          </>
                        ) : (
                          <>
                            <span className="w-2.5 h-2.5 bg-[#58a6ff] rounded-full"></span>
                            <span className="text-xs text-[#58a6ff] font-bold uppercase tracking-wider">Boucle complétée / En attente</span>
                          </>
                        )}
                      </div>
                      <span className="text-[10px] text-gray-500 font-mono">Dernier ping : {agenticLoopStatus.updated_at || '-'}</span>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <span className="text-[10px] uppercase font-bold text-gray-500 block">Itération Active</span>
                        <span className="text-lg font-bold text-white font-mono">
                          {agenticLoopStatus.current_iteration || 0} <span className="text-xs text-gray-400">/ {agenticLoopStatus.max_iterations || 100}</span>
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase font-bold text-gray-500 block">Progression Trials</span>
                        <span className="text-lg font-bold text-white font-mono">
                          {agenticLoopStatus.current_trial_num || 0} <span className="text-xs text-gray-400">/ {agenticLoopStatus.total_trials || 150}</span>
                        </span>
                      </div>
                    </div>

                    {/* Progression bars */}
                    <div className="space-y-1.5 pt-1">
                      <div className="flex justify-between text-[10px] text-gray-400 font-mono">
                        <span>Progression Itération</span>
                        <span>{(((agenticLoopStatus.current_trial_num || 0) / (agenticLoopStatus.total_trials || 150)) * 100).toFixed(0)}%</span>
                      </div>
                      <div className="w-full bg-[#161b22] rounded-full h-1.5 border border-[#30363d] overflow-hidden">
                        <div 
                          className="bg-[#2ea043] h-full transition-all duration-300"
                          style={{ width: `${((agenticLoopStatus.current_trial_num || 0) / (agenticLoopStatus.total_trials || 150)) * 100}%` }}
                        ></div>
                      </div>

                      <div className="flex justify-between text-[10px] text-gray-400 font-mono pt-1">
                        <span>Progression Boucle Globale</span>
                        <span>{(((agenticLoopStatus.current_iteration || 0) / (agenticLoopStatus.max_iterations || 100)) * 100).toFixed(0)}%</span>
                      </div>
                      <div className="w-full bg-[#161b22] rounded-full h-1.5 border border-[#30363d] overflow-hidden">
                        <div 
                          className="bg-[#1f6feb] h-full transition-all duration-300"
                          style={{ width: `${((agenticLoopStatus.current_iteration || 0) / (agenticLoopStatus.max_iterations || 100)) * 100}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>

                  {/* KPI Cards row */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[10px] uppercase font-bold text-gray-500 block">Meilleur PnL OOS</span>
                      <span className="text-base font-bold text-[#3fb950] font-mono">
                        {agenticLoopStatus.history && agenticLoopStatus.history.length > 0
                          ? Math.max(0, ...agenticLoopStatus.history.map(h => h.oos_pnl || 0)).toFixed(2)
                          : '0.00'}%
                      </span>
                    </div>
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[10px] uppercase font-bold text-gray-500 block">Meilleur Sortino</span>
                      <span className="text-base font-bold text-[#58a6ff] font-mono">
                        {agenticLoopStatus.history && agenticLoopStatus.history.length > 0
                          ? Math.max(0, ...agenticLoopStatus.history.map(h => (h.metrics && h.metrics.sortino) || h.sortino || 0)).toFixed(2)
                          : '0.00'}
                      </span>
                    </div>
                    <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 text-center">
                      <span className="text-[10px] uppercase font-bold text-gray-500 block">Max Trades</span>
                      <span className="text-base font-bold text-orange-400 font-mono">
                        {agenticLoopStatus.history && agenticLoopStatus.history.length > 0
                          ? Math.max(0, ...agenticLoopStatus.history.map(h => h.trades_count || 0))
                          : 0}
                      </span>
                    </div>
                  </div>

                  {/* Iterations Log Table */}
                  <div className="flex-1 overflow-y-auto max-h-[350px] border border-[#30363d] rounded-lg">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-[#0d1117] text-[#8b949e] border-b border-[#30363d] uppercase tracking-wider text-[10px] sticky top-0">
                          <th className="p-3 font-semibold text-center w-12">Iter</th>
                          <th className="p-3 font-semibold">Alg/Fmt</th>
                          <th className="p-3 font-semibold text-right">OOS PnL</th>
                          <th className="p-3 font-semibold text-center">Trades</th>
                          <th className="p-3 font-semibold text-right">Sortino</th>
                          <th className="p-3 font-semibold text-right">MaxDD</th>
                          <th className="p-3 font-semibold text-center">Rapport</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#30363d]">
                        {agenticLoopStatus.history && agenticLoopStatus.history.slice().reverse().map((iter) => {
                          const optModel = iter.params.model_type || 'lgb';
                          const optFormat = iter.params.target_format === 'classification' ? 'Class' : 'Reg';
                          const isExpanded = openIteration === iter.iteration;
                          
                          return (
                            <React.Fragment key={iter.iteration}>
                              <tr 
                                className={`hover:bg-[#161b22] font-mono cursor-pointer transition-colors ${
                                  isExpanded ? 'bg-[#1f6feb]/5' : ''
                                }`}
                                onClick={() => setOpenIteration(isExpanded ? null : iter.iteration)}
                              >
                                <td className="p-3 text-center text-gray-500 font-semibold">{iter.iteration}</td>
                                <td className="p-3 text-gray-400">
                                  {optModel.substring(0,3)}/{optFormat}
                                </td>
                                <td className={`p-3 text-right font-bold ${
                                  iter.oos_pnl > 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                                }`}>
                                  {iter.oos_pnl.toFixed(2)}%
                                </td>
                                <td className="p-3 text-center text-white">{iter.trades_count}</td>
                                <td className="p-3 text-right text-[#58a6ff]">{(iter.metrics && iter.metrics.sortino) ? iter.metrics.sortino.toFixed(2) : (iter.sortino ? iter.sortino.toFixed(2) : '-')}</td>
                                <td className="p-3 text-right text-orange-400">{(iter.max_drawdown * 100.0).toFixed(2)}%</td>
                                <td className="p-3 text-center text-gray-500">
                                  <i className={`fa-solid ${isExpanded ? 'fa-chevron-up' : 'fa-chevron-down'} text-xs`}></i>
                                </td>
                              </tr>
                              {isExpanded && (
                                <tr className="bg-[#0d1117]/50">
                                  <td colSpan="7" className="p-4 text-xs space-y-3 font-sans border-b border-[#30363d]">
                                    <div className="bg-[#161b22]/50 border border-[#30363d] rounded-lg p-3">
                                      <p className="text-[#58a6ff] font-bold mb-1.5 flex items-center uppercase tracking-wider text-[10px]">
                                        <i className="fa-solid fa-magnifying-glass-chart mr-1.5"></i> Analyse Rationale
                                      </p>
                                      <p className="text-gray-300 leading-relaxed font-mono text-[11px]">{iter.rationale}</p>
                                    </div>
                                    <div className="bg-[#161b22]/50 border border-[#30363d] rounded-lg p-3">
                                      <p className="text-yellow-500 font-bold mb-1.5 flex items-center uppercase tracking-wider text-[10px]">
                                        <i className="fa-solid fa-arrow-right-long mr-1.5"></i> Décision & Prochaine Étape
                                      </p>
                                      <p className="text-gray-300 leading-relaxed font-mono text-[11px]">{iter.next_steps}</p>
                                    </div>
                                    <div className="flex flex-wrap gap-x-4 gap-y-1.5 pt-1 font-mono text-[10px] text-gray-500">
                                      <span>• Horizon : {iter.params.hold_candles || 1} klines</span>
                                      <span>• Seuil Cible : {iter.params.target_threshold ? iter.params.target_threshold.toFixed(2) : '-'}%</span>
                                      <span>• Stop Loss : {iter.params.sl_ratio ? (iter.params.sl_ratio * (iter.params.target_threshold || 1)).toFixed(2) : '-'}%</span>
                                      <span>• Features Top : {iter.params.top_n_features || '-'}</span>
                                      <span>• IS Length : {iter.params.is_length_days || '-'}d</span>
                                    </div>
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )
            )}
          </div>
        </div>

      </div>
    </div>
  );
};
