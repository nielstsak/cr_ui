
import React, { useState } from 'react';
import { useMarketStore } from '../../entities/market/store';
import { marketApi } from '../../entities/market/api';

export const ResampleForm = ({ selectedSymbol, availableTfs }) => {
  const [input, setInput] = useState('');
  const [isResampling, setIsResampling] = useState(false);
  const fetchLocalPairs = useMarketStore((state) => state.fetchLocalPairs);
  const fetchStats = useMarketStore((state) => state.fetchStats);
  const fetchVbtInfo = useMarketStore((state) => state.fetchVbtInfo);

  const handleResample = async () => {
    if (!input.trim() || !selectedSymbol) return;
    setIsResampling(true);
    const tfs = input.split(';').map((s) => s.trim()).filter(Boolean);
    try {
      for (const tf of tfs) {
        await marketApi.addTimeframe(selectedSymbol, tf);
      }
      await fetchLocalPairs();
      await fetchStats(selectedSymbol);
      await fetchVbtInfo(selectedSymbol);
    } catch (e) {
      console.error(e);
    }
    setInput('');
    setIsResampling(false);
  };

  const baseTf = availableTfs.includes('5m') ? '5m' : (availableTfs[0] || 'N/A');

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm space-y-4">
        <h4 className="text-white text-xs font-bold uppercase tracking-wider border-b border-[#30363d] pb-2 text-[#58a6ff]">
          <i className="fa-solid fa-clock mr-2"></i> Timeframes Actuels
        </h4>
        <div className="flex justify-between items-center text-sm bg-[#0d1117] border border-[#30363d] p-3 rounded-lg">
          <span className="text-[#8b949e] font-semibold">Timeframe de Base :</span>
          <span className="text-white font-mono font-bold bg-[#1f6feb]/20 text-[#58a6ff] px-2 py-0.5 rounded border border-[#1f6feb]/30">{baseTf}</span>
        </div>
        <div className="flex justify-between items-center text-sm bg-[#0d1117] border border-[#30363d] p-3 rounded-lg">
          <span className="text-[#8b949e] font-semibold">Présents sur le disque :</span>
          <span className="text-white font-mono text-xs text-right break-words pl-4">{availableTfs.join(', ') || 'Aucun'}</span>
        </div>
      </div>

      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm flex flex-col justify-between space-y-3">
        <div>
          <h4 className="text-white text-xs font-bold uppercase tracking-wider border-b border-[#30363d] pb-2 text-[#58a6ff]">
            <i className="fa-solid fa-layer-group mr-2"></i> Resample Base Timeframe
          </h4>
          <p className="text-xs text-gray-500 mt-2">Générez des TF supérieurs. Séparateur "<strong className="text-gray-300">;</strong>" (ex: <span className="font-mono">15m; 1h</span>).</p>
        </div>
        <div className="flex space-x-3">
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)} placeholder="15m; 1h; 4h" className="flex-1 bg-[#0d1117] border border-[#30363d] rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono shadow-inner" />
          <button onClick={handleResample} disabled={isResampling || !input.trim()} className="px-5 py-2 bg-[#1f6feb] hover:bg-[#388bfd] disabled:opacity-50 text-white text-xs font-bold uppercase rounded-lg transition-colors shadow-sm whitespace-nowrap flex items-center">
            {isResampling ? <><i className="fa-solid fa-circle-notch fa-spin mr-2"></i> En cours...</> : 'Activer Resample'}
          </button>
        </div>
      </div>
    </div>
  );
};