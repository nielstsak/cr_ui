
import React from 'react';
import { useMarketStore } from '../entities/market/store';
import { useIndicatorStore } from '../entities/indicators/store';
import { marketApi } from '../entities/market/api.js';
import { IngestionForm } from '../features/DataIngestion/IngestionForm.jsx';
import InformationsData from '../components/InformationsData.jsx';

export const IngestionPage = () => {
  const activeSymbol = useMarketStore((state) => state.activeSymbol);
  const setActiveSymbol = useMarketStore((state) => state.setActiveSymbol);
  const localPairs = useMarketStore((state) => state.localPairs);
  const fetchLocalPairs = useMarketStore((state) => state.fetchLocalPairs);
  const fetchStats = useMarketStore((state) => state.fetchStats);
  const setCalculatedIndicators = useIndicatorStore((state) => state.setCalculatedIndicators);

  const handleRefreshSymbol = async (symbol) => {
    try {
      await fetch(`http://localhost:8000/api/ingestion/refresh/${symbol}`, { method: 'POST' });
      await fetchLocalPairs();
      await fetchStats(symbol);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteSymbol = async (symbol) => {
    if (confirm(`Voulez-vous purger complètement les données de la paire ${symbol} ?`)) {
      try {
        await marketApi.deleteSymbol(symbol);
        await fetchLocalPairs();
        setActiveSymbol('');
      } catch (e) {
        console.error(e);
      }
    }
  };

  return (
    <div className="p-6">
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 h-full">
        
        <div className="xl:col-span-4 flex flex-col space-y-6">
          <IngestionForm />

          <div className="bg-[#161b22] border border-[#30363d] rounded-xl shadow-sm flex flex-col flex-1">
            <div className="p-5 border-b border-[#30363d] flex justify-between items-center">
              <h3 className="text-[#58a6ff] text-sm font-bold uppercase tracking-wider flex items-center">
                <i className="fa-solid fa-folder-tree mr-2.5"></i> Bloc 2 : Fichiers Locaux
              </h3>
            </div>
            
            <div className="p-4 overflow-y-auto flex-1 max-h-[400px]">
              {localPairs.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full py-10 text-gray-500 text-xs italic">
                  <i className="fa-solid fa-file-circle-xmark text-2xl mb-2 text-[#30363d]"></i>
                  Aucune paire téléchargée.
                </div>
              ) : (
                <div className="space-y-2">
                  {localPairs.map((p) => (
                    <div 
                      key={p.symbol}
                      onClick={() => setActiveSymbol(p.symbol)}
                      className={`p-3 rounded-lg border text-sm cursor-pointer transition-all flex flex-col ${
                        activeSymbol === p.symbol 
                          ? 'bg-[#1f6feb]/10 border-[#1f6feb] text-white shadow-inner' 
                          : 'bg-[#0d1117] border-[#30363d] text-gray-400 hover:bg-[#161b22]'
                      }`}
                    >
                      <div className="flex justify-between items-center mb-2">
                        <span className="font-bold font-mono text-base">{p.symbol}</span>
                        <div className="flex space-x-2">
                          <button onClick={(e) => { e.stopPropagation(); handleRefreshSymbol(p.symbol); }} className="text-gray-500 hover:text-white transition-colors" title="Actualiser">
                            <i className="fa-solid fa-rotate-right"></i>
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); handleDeleteSymbol(p.symbol); }} className="text-red-900 hover:text-red-500 transition-colors" title="Supprimer">
                            <i className="fa-solid fa-trash"></i>
                          </button>
                        </div>
                      </div>
                      <span className="text-[10px] font-mono text-gray-500 truncate">
                        Timeframes: {p.timeframe}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="xl:col-span-8 flex flex-col">
          <div className="bg-[#0d1117] border border-[#30363d] rounded-xl p-6 flex-1 shadow-inner h-full">
            <h3 className="text-[#c9d1d9] text-lg font-bold uppercase tracking-wider border-b border-[#30363d] pb-4 mb-6 flex items-center">
              <i className="fa-solid fa-microchip mr-3 text-[#1f6feb]"></i> Bloc 3 : Informations Symbole ({activeSymbol || 'Aucun'})
            </h3>
            <InformationsData />
          </div>
        </div>

      </div>
    </div>
  );
};