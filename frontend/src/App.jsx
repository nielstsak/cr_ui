import React, { useEffect, useState } from 'react';
import useAppStore from './store/useAppStore';

// Modales & Vues Modulaires du projet
import IngestionModal from './components/IngestionModal';
import IndicatorSettingsModal from './components/IndicatorSettingsModal';
import InformationsData from './components/InformationsData';

import ChartingView from './components/ChartingView';
import LaggedIndicatorsView from './components/LaggedIndicatorsView';
import SeasonalityView from './components/SeasonalityView';
import VolatilityView from './components/VolatilityView';
import HMMRegimeView from './components/HMMRegimeView';
import VSAView from './components/VSAView';

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
    error,
    localPairs,
    fetchLocalPairs,
    deleteSymbol,
    refreshSymbol,
    addTimeframe
  } = useAppStore();

  const [activeTab, setActiveTab] = useState('ingestion'); // 'ingestion' est la page d'administration par défaut
  const [isIngestionModalOpen, setIsIngestionModalOpen] = useState(false);
  const [isIndicatorModalOpen, setIsIndicatorModalOpen] = useState(false);
  const [targetTf, setTargetTf] = useState('15m');
  const [activeTaskId, setActiveTaskId] = useState(null);
  const [taskProgress, setTaskProgress] = useState(0);

  useEffect(() => {
    fetchSymbols();
    fetchLocalPairs();
  }, [fetchSymbols, fetchLocalPairs]);

  // Surveillance et polling de la progression de la tâche active si elle existe
  useEffect(() => {
    if (!activeTaskId) return;

    const interval = setInterval(async () => {
      try {
        const response = await fetch(`http://localhost:8000/api/tasks/${activeTaskId}`);
        if (response.ok) {
          const task = await response.json();
          setTaskProgress(task.progress);
          
          if (task.status === 'completed' || task.status === 'failed') {
            clearInterval(interval);
            setActiveTaskId(null);
            setTaskProgress(0);
            fetchLocalPairs();
            if (activeSymbol) {
              // Recharger les métadonnées et sessions de la paire active
              setActiveSymbol(activeSymbol);
            }
          }
        }
      } catch (err) {
        clearInterval(interval);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [activeTaskId, activeSymbol, fetchLocalPairs, setActiveSymbol]);

  const ActiveComponent = TABS.find(t => t.id === activeTab)?.component || ChartingView;

  const handleRefreshSymbol = async () => {
    if (!activeSymbol) return;
    const taskId = await refreshSymbol(activeSymbol);
    if (taskId) {
      setActiveTaskId(taskId);
    }
  };

  const handleDeleteSymbol = async () => {
    if (!activeSymbol) return;
    if (confirm(`Voulez-vous purger complètement les données locales de la paire ${activeSymbol} ?`)) {
      await deleteSymbol(activeSymbol);
    }
  };

  const handleAddTimeframe = async () => {
    if (!activeSymbol) return;
    await addTimeframe(activeSymbol, targetTf);
  };

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] font-sans flex flex-col">
      <header className="sticky top-0 z-40 bg-[#161b22] border-b border-[#30363d] px-6 py-4 flex items-center justify-between shadow-sm">
        <div className="flex items-center space-x-6">
          <h1 className="text-xl font-bold text-white tracking-wider flex items-center select-none">
            <span className="text-[#1f6feb] mr-2">💎</span> TradingVBT
          </h1>
          
          <div className="flex items-center space-x-4 border-l border-[#30363d] pl-6">
            <div className="flex items-center space-x-2">
              <span className="text-xs text-[#8b949e] uppercase tracking-wider font-semibold">Symbole</span>
              <select 
                value={activeSymbol || ''} 
                onChange={(e) => setActiveSymbol(e.target.value)}
                disabled={isLoading}
                className="bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-[#58a6ff] font-mono cursor-pointer"
              >
                {symbols.length === 0 && <option value="">Aucune Paire</option>}
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
                className="bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 text-sm text-white cursor-pointer"
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
            className="px-4 py-1.5 text-sm border border-[#30363d] bg-[#0d1117] hover:bg-[#30363d] text-[#c9d1d9] rounded transition-colors flex items-center font-medium"
          >
            <i className="fa-solid fa-sliders mr-2 text-[#8b949e]"></i> Config. Indicateurs
          </button>
          <button 
            onClick={() => setIsIngestionModalOpen(true)}
            className="px-4 py-1.5 text-sm bg-[#1f6feb] hover:bg-[#388bfd] text-white rounded transition-colors shadow-sm flex items-center font-bold"
          >
            <i className="fa-solid fa-cloud-arrow-down mr-2"></i> Nouveau Run MTF
          </button>
        </div>
      </header>

      {/* Barre d'onglets du Workspace principal */}
      <div className="bg-[#161b22] border-b border-[#30363d] px-6 flex space-x-2 overflow-x-auto">
        <button
          onClick={() => setActiveTab('ingestion')}
          className={`px-5 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors flex items-center ${
            activeTab === 'ingestion' 
              ? 'border-[#1f6feb] text-white bg-[#0d1117]' 
              : 'border-transparent text-[#8b949e] hover:text-[#c9d1d9] hover:bg-[#30363d] bg-transparent'
          }`}
        >
          <i className="fa-solid fa-database mr-2 text-brand-500"></i> Ingestion Données
        </button>
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
        {isLoading && !activeSession && activeTab !== 'ingestion' ? (
          <div className="flex items-center justify-center h-full text-[#8b949e] p-10">
            <i className="fa-solid fa-circle-notch fa-spin mr-3"></i> Synchronisation...
          </div>
        ) : activeTab === 'ingestion' ? (
          
          /* VIEW : Ingestion des Données Historiques */
          <div className="p-6 space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* CONTAINER : Configuration rapide de l'ingestion */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4">
                <h3 className="text-[#58a6ff] text-xs font-bold uppercase tracking-wider border-b border-[#30363d] pb-2">
                  <i className="fa-solid fa-gears mr-2"></i> Configuration &amp; Console
                </h3>
                <p className="text-xs text-gray-400">
                  Utilisez le bouton <strong className="text-white">"Nouveau Run MTF"</strong> en haut à droite pour importer une nouvelle paire d'actifs.
                </p>
                <div className="bg-[#0d1117] border border-[#30363d] rounded p-4 text-xs font-mono text-gray-400 space-y-1 max-h-[140px] overflow-y-auto">
                  <div>[Bridge 5555] Actif et en attente...</div>
                  {activeTaskId && (
                    <div className="text-brand-500 font-bold">
                      [Task Ingestion] Tâche active, progression : {taskProgress}%
                    </div>
                  )}
                </div>
              </div>

              {/* CONTAINER : Paires Ingestées & Statuts */}
              <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 lg:col-span-2">
                <div className="flex justify-between items-center border-b border-[#30363d] pb-2">
                  <h3 className="text-white text-xs font-bold uppercase tracking-wider">
                    <i className="fa-solid fa-server mr-2 text-[#58a6ff]"></i>
                    Paires Ingestées &amp; Actions de Gestion
                  </h3>
                  <div className="flex space-x-2">
                    <button 
                      onClick={handleRefreshSymbol} 
                      disabled={!activeSymbol}
                      className="text-xs font-semibold bg-gray-800 hover:bg-gray-700 disabled:opacity-50 px-3 py-1.5 rounded transition-colors"
                    >
                      <i className="fa-solid fa-sync mr-1"></i> Actualiser
                    </button>
                    <button 
                      onClick={handleDeleteSymbol} 
                      disabled={!activeSymbol}
                      className="text-xs font-semibold bg-red-950/80 text-red-400 hover:bg-red-900 disabled:opacity-50 px-3 py-1.5 rounded transition-colors"
                    >
                      <i className="fa-solid fa-trash mr-1"></i> Supprimer
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Table / List */}
                  <div className="border border-[#30363d] bg-[#0d1117] rounded p-2.5 max-h-[150px] overflow-y-auto space-y-1.5">
                    {localPairs.length === 0 ? (
                      <div className="text-center py-6 text-gray-500 text-xs">Aucun symbole sur disque.</div>
                    ) : (
                      localPairs.map(p => (
                        <div 
                          key={p.symbol}
                          onClick={() => setActiveSymbol(p.symbol)}
                          className={`p-2 rounded border text-xs font-mono font-bold cursor-pointer transition-colors flex justify-between items-center ${
                            activeSymbol === p.symbol 
                              ? 'bg-[#1f6feb]/15 border-[#1f6feb] text-white' 
                              : 'bg-[#161b22] border-[#30363d] text-gray-300 hover:bg-gray-800'
                          }`}
                        >
                          <span>{p.symbol}</span>
                          <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
                            p.status === 'ingesting' ? 'bg-[#1f6feb]/20 text-[#1f6feb] animate-pulse' : 'bg-gray-850 text-gray-400'
                          }`}>
                            {p.status}
                          </span>
                        </div>
                      ))
                    )}
                  </div>

                  {/* Resampling trigger right pane */}
                  <div className="bg-[#0d1117] border border-[#30363d] rounded p-3 flex flex-col justify-between text-xs">
                    <span className="text-gray-400">Générer une unité de temps manquante :</span>
                    <div className="flex space-x-2 mt-2">
                      <select 
                        value={targetTf} 
                        onChange={(e) => setTargetTf(e.target.value)}
                        className="bg-[#161b22] border border-[#30363d] rounded px-2 py-1 text-white font-mono flex-1 cursor-pointer"
                      >
                        <option value="15m">15m</option>
                        <option value="30m">30m</option>
                        <option value="1h">1h</option>
                        <option value="2h">2h</option>
                        <option value="4h">4h</option>
                        <option value="6h">6h</option>
                        <option value="8h">8h</option>
                        <option value="12h">12h</option>
                        <option value="1d">1d</option>
                      </select>
                      <button 
                        onClick={handleAddTimeframe}
                        className="bg-brand-600 hover:bg-brand-500 font-bold px-3 py-1 rounded transition-colors text-white"
                      >
                        Ajouter TF
                      </button>
                    </div>
                  </div>
                </div>
              </div>

            </div>

            {/* CONTAINER : Informations & Statistiques Descriptives */}
            <InformationsData />

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