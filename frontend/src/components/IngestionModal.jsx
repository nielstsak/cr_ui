import React, { useState, useEffect } from 'react';
import useAppStore from '../store/useAppStore.js';

/**
 * Composant IngestionBlock (anciennement IngestionModal) - Bloc 1 : Acquisition
 * Expose les arguments natifs de vectorbtpro pour l'ingestion de données.
 */
const IngestionModal = () => {
  const executeVbtFetch = useAppStore(state => state.executeVbtFetch);
  const fetchLocalPairs = useAppStore(state => state.fetchLocalPairs);
  const fetchSymbols = useAppStore(state => state.fetchSymbols);
  const setActiveSymbol = useAppStore(state => state.setActiveSymbol);

  // État local des arguments d'acquisition vectorbtpro (Timeframe par défaut : 5m)
  const [fetchParams, setFetchParams] = useState({
    symbol: 'BTCUSDT',
    client: '',
    start: '1 year ago',
    end: 'now',
    timeframe: '5m',
    limit: 1000,
    delay: 0.5,
    show_progress: true
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState(null);
  const [activeTaskId, setActiveTaskId] = useState(null);
  const [taskProgress, setTaskProgress] = useState(0);

  // Polling de la progression de la tâche d'acquisition en arrière-plan
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
            setIsSubmitting(false);
            
            if (task.status === 'completed') {
              setMessage({ type: 'success', text: 'Acquisition terminée avec succès.' });
              await fetchLocalPairs();
              await fetchSymbols();
              setActiveSymbol(fetchParams.symbol.toUpperCase());
            } else {
              setMessage({ type: 'error', text: `Erreur: ${task.error}` });
            }
            
            setTimeout(() => setMessage(null), 4000);
          }
        }
      } catch (err) {
        clearInterval(interval);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [activeTaskId, fetchParams.symbol, fetchLocalPairs, fetchSymbols, setActiveSymbol]);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFetchParams(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleIngest = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setMessage(null);
    setTaskProgress(0);

    const taskId = await executeVbtFetch(fetchParams);
    if (taskId) {
      setActiveTaskId(taskId);
      setMessage({ type: 'info', text: 'Tâche d\'acquisition démarrée...' });
    } else {
      setIsSubmitting(false);
      setMessage({ type: 'error', text: 'Impossible de démarrer la tâche d\'acquisition.' });
    }
  };

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl shadow-sm flex flex-col h-full">
      <div className="p-5 border-b border-[#30363d]">
        <h3 className="text-[#58a6ff] text-sm font-bold uppercase tracking-wider flex items-center">
          <i className="fa-solid fa-cloud-arrow-down mr-2.5"></i> Bloc 1 : Acquisition VectorBT
        </h3>
      </div>
      
      <form onSubmit={handleIngest} className="p-6 space-y-5 flex-1">
        {message && (
          <div className={`p-3 rounded text-xs border font-mono ${
            message.type === 'success' ? 'bg-[#2ea043]/10 text-[#2ea043] border-[#2ea043]/30' : 
            message.type === 'error' ? 'bg-[#f85149]/10 text-[#f85149] border-[#f85149]/30' :
            'bg-[#1f6feb]/10 text-[#58a6ff] border-[#1f6feb]/30'
          }`}>
            {message.text}
            {activeTaskId && <div className="mt-1 font-bold">Progression : {taskProgress}%</div>}
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="block text-[11px] font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Symbol</label>
            <input type="text" name="symbol" value={fetchParams.symbol} onChange={handleChange} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono uppercase" required />
          </div>

          <div className="col-span-2">
            <label className="block text-[11px] font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Client (Optional)</label>
            <input type="text" name="client" value={fetchParams.client} onChange={handleChange} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-gray-400 focus:outline-none focus:border-[#1f6feb] font-mono" placeholder="Configuration dict/string" />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Start</label>
            <input type="text" name="start" value={fetchParams.start} onChange={handleChange} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono" placeholder="ex: 1 year ago" required />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">End</label>
            <input type="text" name="end" value={fetchParams.end} onChange={handleChange} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono" placeholder="ex: now" required />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Timeframe</label>
            <input type="text" name="timeframe" value={fetchParams.timeframe} onChange={handleChange} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono" placeholder="ex: 5m, 1h" required />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Limit</label>
            <input type="number" name="limit" value={fetchParams.limit} onChange={handleChange} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono" />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Delay (s)</label>
            <input type="number" step="0.1" name="delay" value={fetchParams.delay} onChange={handleChange} className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono" />
          </div>

          <div className="flex items-center pt-5">
            <label className="flex items-center space-x-2 text-xs font-semibold text-[#c9d1d9] cursor-pointer hover:text-white">
              <input type="checkbox" name="show_progress" checked={fetchParams.show_progress} onChange={handleChange} className="rounded bg-[#0d1117] border-[#30363d] text-[#1f6feb] focus:ring-[#1f6feb] cursor-pointer" />
              <span>Show Progress</span>
            </label>
          </div>
        </div>

        <div className="pt-4 border-t border-[#30363d]">
          <button 
            type="submit" 
            disabled={isSubmitting}
            className="w-full py-3 bg-[#1f6feb] hover:bg-[#388bfd] disabled:opacity-50 text-white text-xs font-bold uppercase tracking-wider rounded transition-colors shadow-sm"
          >
            {isSubmitting ? <><i className="fa-solid fa-circle-notch fa-spin mr-2"></i> Extraction VBT Pro...</> : 'Télécharger via VectorBT'}
          </button>
        </div>
      </form>
    </div>
  );
};

export default IngestionModal;