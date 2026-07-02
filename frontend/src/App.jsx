import React, { useEffect, useState } from 'react';
import useAppStore from './store/useAppStore';
import IngestionModal from './components/IngestionModal';
import IndicatorSettingsModal from './components/IndicatorSettingsModal';

import ChartingView from './components/views/ChartingView';
import LaggedIndicatorsView from './components/views/LaggedIndicatorsView';
import SeasonalityView from './components/views/SeasonalityView';
import VolatilityView from './components/views/VolatilityView';
import HMMRegimeView from './components/views/HMMRegimeView';
import VSAView from './components/views/VSAView';

const TABS = [
  { id: 'charting', label: '📈 Chart & Indicators', component: ChartingView },
  { id: 'lagged', label: '🔍 Lagged Indicators', component: LaggedIndicatorsView },
  { id: 'seasonality', label: '📅 Seasonality', component: SeasonalityView },
  { id: 'volatility', label: '🌪️ Volatility Clustering', component: VolatilityView },
  { id: 'hmm', label: '📊 HMM Regime Map', component: HMMRegimeView },
  { id: 'vsa', label: '🧬 VSA & Wicks', component: VSAView }
];

function App() {
  const { 
    symbols, 
    activeSymbol, 
    setActiveSymbol, 
    sessions, 
    activeSession, 
    setActiveSession,
    fetchSymbols,
    isLoading,
    error
  } = useAppStore();

  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const [isIngestionModalOpen, setIsIngestionModalOpen] = useState(false);
  const [isIndicatorModalOpen, setIsIndicatorModalOpen] = useState(false);

  useEffect(() => {
    fetchSymbols();
  }, [fetchSymbols]);

  const ActiveComponent = TABS.find(t => t.id === activeTab)?.component || ChartingView;

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] font-sans flex flex-col">
      <header className="sticky top-0 z-40 bg-[#161b22] border-b border-[#30363d] px-6 py-4 flex items-center justify-between shadow-sm">
        <div className="flex items-center space-x-6">
          <h1 className="text-xl font-bold text-white tracking-wider flex items-center">
            <span className="text-[#1f6feb] mr-2">💎</span> TradingVBT
          </h1>
          
          <div className="flex items-center space-x-4 border-l border-[#30363d] pl-6">
            <div className="flex items-center space-x-2">
              <span className="text-xs text-[#8b949e] uppercase tracking-wider font-semibold">Symbole</span>
              <select 
                value={activeSymbol || ''} 
                onChange={(e) => setActiveSymbol(e.target.value)}
                disabled={isLoading}
                className="bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#58a6ff]"
              >
                {symbols.length === 0 && <option value="">Chargement...</option>}
                {symbols.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>

            <div className="flex items-center space-x-2">
              <span className="text-xs text-[#8b949e] uppercase tracking-wider font-semibold">Session</span>
              <select 
                value={activeSession ? activeSession.timestamp : ''} 
                onChange={(e) => {
                  const sess = sessions.find(s => s.timestamp === e.target.value);
                  if (sess) setActiveSession(sess);
                }}
                disabled={isLoading || sessions.length === 0}
                className="bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#58a6ff]"
              >
                {sessions.length === 0 && <option value="">Aucune session</option>}
                {sessions.map(s => (
                  <option key={s.timestamp} value={s.timestamp}>
                    {s.timestamp} ({s.timeframe})
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          {error && <span className="text-[#f85149] text-xs mr-4">{error}</span>}
          <button 
            onClick={() => setIsIndicatorModalOpen(true)}
            className="px-4 py-1.5 text-sm border border-[#30363d] bg-[#0d1117] hover:bg-[#30363d] text-[#c9d1d9] rounded transition-colors flex items-center"
          >
            <i className="fa-solid fa-sliders mr-2 text-[#8b949e]"></i> Config. Indicateurs
          </button>
          <button 
            onClick={() => setIsIngestionModalOpen(true)}
            className="px-4 py-1.5 text-sm bg-[#1f6feb] hover:bg-[#388bfd] text-white rounded transition-colors shadow-sm flex items-center"
          >
            <i className="fa-solid fa-cloud-arrow-down mr-2"></i> Nouveau Run
          </button>
        </div>
      </header>

      <div className="bg-[#161b22] border-b border-[#30363d] px-6 flex space-x-2 overflow-x-auto">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-5 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
              activeTab === tab.id 
                ? 'border-[#1f6feb] text-white bg-[#0d1117]' 
                : 'border-transparent text-[#8b949e] hover:text-[#c9d1d9] hover:bg-[#30363d] bg-transparent'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <main className="flex-1 overflow-y-auto bg-[#0d1117]">
        {isLoading && !activeSession ? (
          <div className="flex items-center justify-center h-full text-[#8b949e]">
            <i className="fa-solid fa-circle-notch fa-spin mr-3"></i> Synchronisation...
          </div>
        ) : (
          <ActiveComponent />
        )}
      </main>

      <IngestionModal 
        isOpen={isIngestionModalOpen} 
        onClose={() => setIsIngestionModalOpen(false)} 
      />
      <IndicatorSettingsModal 
        isOpen={isIndicatorModalOpen} 
        onClose={() => setIsIndicatorModalOpen(false)} 
      />
    </div>
  );
}

export default App;