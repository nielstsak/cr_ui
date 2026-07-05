import React, { useEffect, useState } from 'react';
import useAppStore from './store/useAppStore';

// Vues Modulaires du projet
import IngestionBlock from './components/IngestionModal';
import InformationsData from './components/InformationsData';
import ChartingView from './components/ChartingView';

// Seuls les deux onglets purs restent
const TABS = [
  { id: 'ingestion', label: '📥 Ingestion Données' },
  { id: 'charting', label: '📈 Graphiques & Indicateurs', component: ChartingView }
];

function App() {
  const { 
    activeSymbol, 
    setActiveSymbol, 
    fetchSymbols,
    localPairs,
    fetchLocalPairs,
    deleteSymbol,
    refreshSymbol
  } = useAppStore();

  const [activeTab, setActiveTab] = useState('ingestion');

  useEffect(() => {
    fetchSymbols();
    fetchLocalPairs();
  }, [fetchSymbols, fetchLocalPairs]);

  const ActiveComponent = TABS.find(t => t.id === activeTab)?.component;

  const handleRefreshSymbol = async (symbol) => {
    await refreshSymbol(symbol);
  };

  const handleDeleteSymbol = async (symbol) => {
    if (confirm(`Voulez-vous purger complètement les données de la paire ${symbol} ?`)) {
      await deleteSymbol(symbol);
    }
  };

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] font-sans flex flex-col">
      <header className="sticky top-0 z-40 bg-[#161b22] border-b border-[#30363d] flex items-center shadow-sm overflow-x-auto scrollbar-hide">
        <div className="flex items-center px-6 border-r border-[#30363d] min-w-max">
          <h1 className="text-lg font-bold text-white tracking-wider flex items-center select-none py-4">
            <span className="text-[#1f6feb] mr-2">💎</span> TradingVBT
          </h1>
        </div>
        
        <div className="flex flex-1 items-center px-2">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-5 py-4 text-[13px] font-semibold uppercase tracking-wider whitespace-nowrap transition-colors border-b-2 ${
                activeTab === tab.id 
                  ? 'border-[#1f6feb] text-white bg-[#0d1117]' 
                  : 'border-transparent text-[#8b949e] hover:text-[#c9d1d9] hover:bg-[#30363d] bg-transparent'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto bg-[#0d1117]">
        {activeTab === 'ingestion' ? (
          <div className="p-6">
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 h-full">
              
              <div className="xl:col-span-4 flex flex-col space-y-6">
                <IngestionBlock />

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
                        {localPairs.map(p => (
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
        ) : (
          ActiveComponent && <ActiveComponent />
        )}
      </main>
    </div>
  );
}

export default App;