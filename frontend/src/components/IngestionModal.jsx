import React, { useState } from 'react';
import useAppStore from '../store/useAppStore.js';

/**
 * Modal premium d'acquisition de données historiques Binance.
 * Permet la sélection dynamique de multiples timeframes à rééchantillonner.
 */
const IngestionModal = ({ isOpen, onClose }) => {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [days, setDays] = useState(30);
  const [selectedTfs, setSelectedTfs] = useState(['5m', '15m', '1h']);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState(null);

  const fetchLocalPairs = useAppStore(state => state.fetchLocalPairs);

  const AVAILABLE_TIMEFRAMES = [
    '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'
  ];

  if (!isOpen) return null;

  const handleTfToggle = (tf) => {
    if (tf === '5m') return; // Le timeframe de base 5m est requis et non désactivable
    if (selectedTfs.includes(tf)) {
      setSelectedTfs(selectedTfs.filter(t => t !== tf));
    } else {
      setSelectedTfs([...selectedTfs, tf]);
    }
  };

  const handleIngest = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setMessage(null);

    try {
      const response = await fetch('http://localhost:8000/api/ingestion/start-mtf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol.toUpperCase().replace('/', ''),
          timeframes: selectedTfs,
          days_history: parseInt(days, 10)
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Erreur lors du lancement du processus d\'ingestion MTF.');
      }

      setMessage({ 
        type: 'success', 
        text: `Tâche d'acquisition réseau démarrée avec succès (ID: ${data.task_id.slice(0, 8)})` 
      });
      
      // Actualiser le statut des paires locales immédiatement
      fetchLocalPairs();

      setTimeout(() => {
        onClose();
        setMessage(null);
      }, 2500);

    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-75 backdrop-blur-sm">
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg shadow-2xl w-[480px] flex flex-col overflow-hidden">
        
        {/* En-tête */}
        <div className="flex justify-between items-center p-5 border-b border-[#30363d]">
          <h2 className="text-[#58a6ff] font-semibold uppercase tracking-wider text-sm flex items-center">
            <i className="fa-solid fa-cloud-arrow-down mr-2.5 text-[#1f6feb]"></i> Ingestion de Données MTF
          </h2>
          <button onClick={onClose} className="text-[#8b949e] hover:text-white transition-colors text-sm">
            ✕
          </button>
        </div>
        
        {/* Formulaire de configuration */}
        <form onSubmit={handleIngest} className="p-6 space-y-5">
          {message && (
            <div className={`p-3.5 rounded text-xs border ${
              message.type === 'success' 
                ? 'bg-[#2ea043]/10 text-[#2ea043] border-[#2ea043]/30' 
                : 'bg-[#f85149]/10 text-[#f85149] border-[#f85149]/30'
            }`}>
              {message.text}
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-2">
              Paire d'actifs (Binance Spot)
            </label>
            <input 
              type="text" 
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono uppercase"
              placeholder="Ex: ETHUSDT"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-2">
              Unités de Temps (Multi-Timeframe)
            </label>
            <div className="grid grid-cols-3 gap-2 bg-[#0d1117] p-3 border border-[#30363d] rounded">
              {AVAILABLE_TIMEFRAMES.map(tf => (
                <label key={tf} className="flex items-center space-x-2 text-xs text-[#c9d1d9] cursor-pointer select-none hover:text-white">
                  <input 
                    type="checkbox" 
                    checked={selectedTfs.includes(tf)}
                    disabled={tf === '5m'} // 5m obligatoire comme base
                    onChange={() => handleTfToggle(tf)}
                    className="rounded bg-[#0d1117] border-[#30363d] text-[#1f6feb] focus:ring-[#1f6feb] cursor-pointer disabled:opacity-50"
                  />
                  <span className={tf === '5m' ? 'font-semibold text-[#58a6ff]' : ''}>
                    {tf} {tf === '5m' && ' (Base)'}
                  </span>
                </label>
              ))}
            </div>
            <p className="text-[10px] text-gray-500 mt-2">
              * L'unité 5m est acquise sur le réseau, puis les autres unités cochées sont générées localement par resampling JIT.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-2">
              Historique à récupérer (Jours)
            </label>
            <input 
              type="number" 
              value={days}
              onChange={(e) => setDays(e.target.value)}
              min="1"
              max="730"
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono"
              required
            />
          </div>

          <div className="pt-3 border-t border-[#30363d] flex justify-end space-x-3">
            <button 
              type="button" 
              onClick={onClose}
              className="px-4 py-2 text-xs font-semibold text-[#c9d1d9] hover:text-white transition-colors"
            >
              Annuler
            </button>
            <button 
              type="submit" 
              disabled={isSubmitting}
              className="px-5 py-2 bg-[#1f6feb] hover:bg-[#388bfd] disabled:opacity-50 text-white text-xs font-bold uppercase rounded tracking-wider transition-colors shadow-md"
            >
              {isSubmitting ? 'Acquisition en cours...' : 'Démarrer l\'acquisition'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default IngestionModal;