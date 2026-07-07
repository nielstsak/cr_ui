import React, { useEffect } from 'react';
import { useMarketStore } from '../entities/market/store';
import { useIndicatorStore } from '../entities/indicators/store';
import { useFeatureStore } from '../entities/features/store';
import { useTaskPolling } from '../features/DataIngestion/useTaskPolling';

export const FeatureEngineeringPage = () => {
  const activeSymbol = useMarketStore((state) => state.activeSymbol);
  const setActiveSymbol = useMarketStore((state) => state.setActiveSymbol);
  const localPairs = useMarketStore((state) => state.localPairs);

  const indicatorGroups = useIndicatorStore((state) => state.indicatorGroups);
  const fetchIndicatorGroups = useIndicatorStore((state) => state.fetchIndicatorGroups);

  const selectedTypes = useFeatureStore((state) => state.selectedIndicatorTypes);
  const toggleIndicatorType = useFeatureStore((state) => state.toggleIndicatorType);
  const setSelectedIndicatorTypes = useFeatureStore((state) => state.setSelectedIndicatorTypes);
  
  const deepenedColumns = useFeatureStore((state) => state.deepenedColumns);
  const fetchDeepenedColumns = useFeatureStore((state) => state.fetchDeepenedColumns);
  
  const activeTaskId = useFeatureStore((state) => state.activeTaskId);
  const setTaskId = useFeatureStore((state) => state.setTaskId);
  const isCalculating = useFeatureStore((state) => state.isCalculating);
  const setCalculating = useFeatureStore((state) => state.setCalculating);
  const error = useFeatureStore((state) => state.error);
  const setError = useFeatureStore((state) => state.setError);
  const startFeatureDeepening = useFeatureStore((state) => state.startFeatureDeepening);

  // Load indicator groups on mount
  useEffect(() => {
    fetchIndicatorGroups();
  }, [fetchIndicatorGroups]);

  // Load deepened columns when activeSymbol changes
  useEffect(() => {
    if (activeSymbol) {
      fetchDeepenedColumns(activeSymbol);
    }
  }, [activeSymbol, fetchDeepenedColumns]);

  // Setup task polling
  const { progress, status, error: pollError } = useTaskPolling(activeTaskId, {
    onComplete: () => {
      setCalculating(false);
      setTaskId(null);
      if (activeSymbol) {
        fetchDeepenedColumns(activeSymbol);
      }
    },
    onFailure: (err) => {
      setCalculating(false);
      setTaskId(null);
      setError(err || "Le calcul a échoué.");
    }
  });

  // Handle errors from polling
  useEffect(() => {
    if (pollError) {
      setError(pollError);
    }
  }, [pollError, setError]);

  const handleSelectAll = () => {
    setSelectedIndicatorTypes(Object.keys(indicatorGroups));
  };

  const handleSelectNone = () => {
    setSelectedIndicatorTypes([]);
  };

  const handleAddFeatures = () => {
    if (!activeSymbol) return;
    startFeatureDeepening(activeSymbol);
  };

  // Group names lists
  const groupsList = Object.keys(indicatorGroups);

  return (
    <div className="p-6">
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        
        {/* Left column: Controls */}
        <div className="xl:col-span-5 flex flex-col space-y-6">
          
          {/* Bloc 1: Selection & Actions */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
            <h3 className="text-[#58a6ff] text-sm font-bold uppercase tracking-wider mb-4 flex items-center">
              <i className="fa-solid fa-sliders mr-2.5"></i> Configuration
            </h3>

            {/* Symbol Selector */}
            <div className="mb-5">
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#8b949e] mb-2">
                Paire de trading active
              </label>
              <select
                value={activeSymbol}
                onChange={(e) => setActiveSymbol(e.target.value)}
                className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg p-2.5 text-sm font-mono text-white focus:outline-none focus:border-[#1f6feb]"
              >
                <option value="">-- Sélectionner une paire --</option>
                {localPairs.map((p) => (
                  <option key={p.symbol} value={p.symbol}>
                    {p.symbol} ({p.timeframe})
                  </option>
                ))}
              </select>
            </div>

            {/* Indicator Group Checklist */}
            <div className="mb-5">
              <div className="flex justify-between items-center mb-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-[#8b949e]">
                  Types d'indicateurs à approfondir
                </label>
                <div className="flex space-x-2 text-[10px]">
                  <button 
                    onClick={handleSelectAll} 
                    className="text-[#58a6ff] hover:underline"
                    disabled={isCalculating || groupsList.length === 0}
                  >
                    Tout cocher
                  </button>
                  <span className="text-gray-600">|</span>
                  <button 
                    onClick={handleSelectNone} 
                    className="text-[#58a6ff] hover:underline"
                    disabled={isCalculating}
                  >
                    Tout décocher
                  </button>
                </div>
              </div>

              {groupsList.length === 0 ? (
                <div className="text-xs text-gray-500 italic py-2">
                  Chargement des groupes...
                </div>
              ) : (
                <div className="bg-[#0d1117] border border-[#30363d] rounded-lg p-3 max-h-[300px] overflow-y-auto space-y-2.5">
                  {groupsList.map((group) => {
                    const count = indicatorGroups[group]?.length || 0;
                    return (
                      <label 
                        key={group} 
                        className="flex items-center space-x-3 text-sm cursor-pointer text-[#c9d1d9] hover:text-white transition-colors"
                      >
                        <input
                          type="checkbox"
                          checked={selectedTypes.includes(group)}
                          onChange={() => toggleIndicatorType(group)}
                          disabled={isCalculating}
                          className="rounded border-[#30363d] text-[#1f6feb] focus:ring-0 bg-[#0d1117] h-4 w-4"
                        />
                        <span className="flex-1">{group}</span>
                        <span className="text-xs font-mono text-gray-500 bg-[#161b22] px-1.5 py-0.5 rounded-md border border-[#30363d]">
                          {count}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Actions Button */}
            <button
              onClick={handleAddFeatures}
              disabled={isCalculating || !activeSymbol || selectedTypes.length === 0}
              className={`w-full py-3 rounded-lg text-sm font-bold uppercase tracking-wider transition-colors flex items-center justify-center ${
                isCalculating || !activeSymbol || selectedTypes.length === 0
                  ? 'bg-[#21262d] text-gray-500 cursor-not-allowed border border-[#30363d]'
                  : 'bg-[#238636] hover:bg-[#2ea043] text-white'
              }`}
            >
              {isCalculating ? (
                <>
                  <i className="fa-solid fa-circle-notch fa-spin mr-2"></i>
                  Calcul en cours...
                </>
              ) : (
                <>
                  <i className="fa-solid fa-wand-magic-sparkles mr-2"></i>
                  Ajouter les features
                </>
              )}
            </button>
          </div>

          {/* Task Progress & Logging */}
          {isCalculating && (
            <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
              <h3 className="text-white text-sm font-bold mb-3 flex items-center">
                <i className="fa-solid fa-spinner fa-spin mr-2 text-[#58a6ff]"></i>
                Progression du Calcul
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
                <p className="font-bold">Une erreur est survenue</p>
                <p className="text-xs text-gray-400 mt-1">{error}</p>
              </div>
            </div>
          )}
        </div>

        {/* Right column: Column Validation List */}
        <div className="xl:col-span-7 flex flex-col">
          <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 shadow-sm flex-1 flex flex-col min-h-[450px]">
            <h3 className="text-[#c9d1d9] text-base font-bold uppercase tracking-wider border-b border-[#30363d] pb-4 mb-4 flex items-center">
              <i className="fa-solid fa-clipboard-check mr-2.5 text-[#58a6ff]"></i>
              Validation : Dossier Approfondi ({activeSymbol || 'Aucun'})
            </h3>

            {!activeSymbol ? (
              <div className="flex flex-col items-center justify-center flex-1 py-10 text-gray-500 text-sm italic">
                <i className="fa-solid fa-arrow-left text-2xl mb-3 text-[#30363d]"></i>
                Veuillez sélectionner une paire de trading active dans la configuration.
              </div>
            ) : Object.keys(deepenedColumns).length === 0 ? (
              <div className="flex flex-col items-center justify-center flex-1 py-10 text-gray-500 text-sm italic text-center px-6">
                <i className="fa-solid fa-folder-open text-3xl mb-3 text-[#30363d]"></i>
                Aucune feature approfondie n'a encore été générée pour la paire <span className="font-mono text-white not-italic">{activeSymbol}</span>.
                <p className="text-xs text-gray-500 mt-2 max-w-md">
                  Sélectionnez des types d'indicateurs à gauche puis cliquez sur "Ajouter les features" pour générer les variations temporelles optimisées.
                </p>
              </div>
            ) : (
              <div className="space-y-6 overflow-y-auto flex-1 max-h-[550px] pr-2 scrollbar-thin">
                {Object.entries(deepenedColumns).map(([tf, cols]) => (
                  <div key={tf} className="bg-[#0d1117] border border-[#30363d] rounded-lg p-4">
                    <div className="flex justify-between items-center border-b border-[#30363d] pb-2 mb-3">
                      <span className="text-sm font-bold font-mono text-[#58a6ff] uppercase tracking-wider">
                        ⏰ Timeframe : {tf}
                      </span>
                      <span className="text-xs font-mono text-gray-500">
                        {cols.length} feature(s)
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {cols.map((col) => (
                        <span 
                          key={col} 
                          className="text-[11px] font-mono text-gray-300 bg-[#161b22] border border-[#30363d] px-2 py-1 rounded hover:border-[#1f6feb] transition-colors cursor-default"
                          title={col}
                        >
                          {col}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};
