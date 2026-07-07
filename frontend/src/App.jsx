
import React, { useEffect, useState } from 'react';
import { useMarketStore } from './entities/market/store';
import { IngestionPage } from './pages/IngestionPage';
import { ChartingPage } from './pages/ChartingPage';
import { FeatureEngineeringPage } from './pages/FeatureEngineeringPage';

const TABS = [
  { id: 'ingestion', label: '📥 Ingestion Données', component: IngestionPage },
  { id: 'charting', label: '📈 Graphiques & Indicateurs', component: ChartingPage },
  { id: 'feature-engineering', label: '⚙️ Feature Engineering', component: FeatureEngineeringPage }
];

function App() {
  const fetchSymbols = useMarketStore((state) => state.fetchLocalPairs);
  const fetchLocalPairs = useMarketStore((state) => state.fetchLocalPairs);

  const [activeTab, setActiveTab] = useState('ingestion');

  useEffect(() => {
    fetchSymbols();
    fetchLocalPairs();
  }, [fetchSymbols, fetchLocalPairs]);

  const ActiveComponent = TABS.find((t) => t.id === activeTab)?.component;

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] font-sans flex flex-col">
      <header className="sticky top-0 z-40 bg-[#161b22] border-b border-[#30363d] flex items-center shadow-sm overflow-x-auto scrollbar-hide">
        <div className="flex items-center px-6 border-r border-[#30363d] min-w-max">
          <h1 className="text-lg font-bold text-white tracking-wider flex items-center select-none py-4">
            <span className="text-[#1f6feb] mr-2">💎</span> TradingVBT
          </h1>
        </div>
        
        <div className="flex flex-1 items-center px-2">
          {TABS.map((tab) => (
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
        {ActiveComponent && <ActiveComponent />}
      </main>
    </div>
  );
}

export default App;