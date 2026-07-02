import React, { useState } from 'react';

const IngestionModal = ({ isOpen, onClose }) => {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [days, setDays] = useState(30);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState(null);

  if (!isOpen) return null;

  const handleIngest = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setMessage(null);

    try {
      const response = await fetch('http://localhost:8000/api/ingestion/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol.toUpperCase(),
          timeframe: '5m', // Forcé en backend, source de vérité
          days_history: parseInt(days, 10)
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Erreur lors du lancement de l\'ingestion');
      }

      setMessage({ type: 'success', text: `Tâche démarrée en arrière-plan (ID: ${data.task_id.slice(0, 8)}...)` });
      
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60 backdrop-blur-sm">
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg shadow-xl w-[450px] flex flex-col">
        <div className="flex justify-between items-center p-5 border-b border-[#30363d]">
          <h2 className="text-[#58a6ff] font-semibold uppercase tracking-wider">
            <i className="fa-solid fa-cloud-arrow-down mr-2"></i> Ingestion de Données
          </h2>
          <button onClick={onClose} className="text-[#8b949e] hover:text-white transition-colors">
            ✕
          </button>
        </div>
        
        <form onSubmit={handleIngest} className="p-6 space-y-5">
          {message && (
            <div className={`p-3 rounded text-sm ${message.type === 'success' ? 'bg-[#2ea043] bg-opacity-10 text-[#2ea043] border border-[#2ea043]' : 'bg-[#f85149] bg-opacity-10 text-[#f85149] border border-[#f85149]'}`}>
              {message.text}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-[#c9d1d9] mb-1.5">Symbole Binance (Pair)</label>
            <input 
              type="text" 
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-white focus:outline-none focus:border-[#58a6ff] font-mono"
              placeholder="Ex: ETHUSDT"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[#c9d1d9] mb-1.5">Historique (Jours)</label>
            <input 
              type="number" 
              value={days}
              onChange={(e) => setDays(e.target.value)}
              min="1"
              max="1000"
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-white focus:outline-none focus:border-[#58a6ff] font-mono"
              required
            />
          </div>
          
          <div className="pt-2 text-xs text-[#8b949e]">
            <p>La donnée sera acquise avec une granularité stricte de <strong>5 minutes</strong>. Les autres unités de temps seront rééchantillonnées dynamiquement par le moteur Numba.</p>
          </div>

          <div className="pt-4 flex justify-end">
            <button 
              type="button" 
              onClick={onClose}
              className="px-4 py-2 text-[#c9d1d9] hover:text-white mr-3 transition-colors"
            >
              Annuler
            </button>
            <button 
              type="submit" 
              disabled={isSubmitting}
              className="px-6 py-2 bg-[#1f6feb] hover:bg-[#388bfd] disabled:opacity-50 text-white font-medium rounded transition-colors shadow-sm"
            >
              {isSubmitting ? 'Démarrage...' : 'Lancer l\'acquisition'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default IngestionModal;