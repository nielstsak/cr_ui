
// frontend/src/widgets/ChartWorkspace.jsx
import React, { useEffect, useState } from 'react';
import { useMarketStore } from '../entities/market/store';
import { useChartingStore } from '../entities/charting/store';
import { useMultiTimeframeData } from '../features/ChartEngine/useMultiTimeframeData';
import { usePlotlyBuilder } from '../features/ChartEngine/usePlotlyBuilder';
import { OhlcvCanvas } from '../features/ChartEngine/OhlcvCanvas';
import { VisualConfigModal } from '../features/IndicatorSettings/VisualConfigModal';
import { ResampleForm } from '../features/ChartEngine/ResampleForm';

const SymbolSelector = ({ localPairs, selectedSymbol, onSelect }) => {
  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm">
      <label className="block text-xs font-bold text-[#8b949e] uppercase tracking-wider mb-3 flex items-center">
        <i className="fa-solid fa-magnifying-glass-chart mr-2 text-[#58a6ff]"></i> 
        1. Sélection du Symbole Local
      </label>
      <select
        value={selectedSymbol}
        onChange={(e) => onSelect(e.target.value)}
        className="w-full md:w-1/3 bg-[#0d1117] border border-[#30363d] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono cursor-pointer shadow-inner"
      >
        <option value="" disabled>-- Sélectionnez un symbole --</option>
        {localPairs.map((p) => (
          <option key={p.symbol} value={p.symbol}>{p.symbol}</option>
        ))}
      </select>
    </div>
  );
};

export const ChartWorkspace = () => {
  const localPairs = useMarketStore((state) => state.localPairs);
  const activeSymbol = useMarketStore((state) => state.activeSymbol);
  const setActiveSymbol = useMarketStore((state) => state.setActiveSymbol);
  const descStats = useMarketStore((state) => state.descStats);
  const fetchStats = useMarketStore((state) => state.fetchStats);
  const isLoading = useChartingStore((state) => state.isLoading);

  const [selectedTf, setSelectedTf] = useState('');
  const [isVisualsModalOpen, setIsVisualsModalOpen] = useState(false);

  const currentPair = localPairs.find((p) => p.symbol === activeSymbol);
  const availableTfs = currentPair ? currentPair.timeframe.split(',').map((s) => s.trim()) : [];

  useEffect(() => {
    if (localPairs.length > 0) {
      const hasActive = localPairs.some((p) => p.symbol === activeSymbol);
      if (!hasActive) {
        setActiveSymbol(localPairs[0].symbol);
      }
    }
  }, [localPairs, activeSymbol, setActiveSymbol]);

  useEffect(() => {
    if (activeSymbol) {
      fetchStats(activeSymbol);
    }
  }, [activeSymbol, fetchStats]);

  useEffect(() => {
    if (availableTfs.length > 0 && !selectedTf) {
      setSelectedTf(availableTfs.includes('5m') ? '5m' : availableTfs[0]);
    }
  }, [availableTfs, selectedTf]);

  useMultiTimeframeData(selectedTf);
  const { traces, layout } = usePlotlyBuilder(selectedTf);

  return (
    <div className="space-y-6">
      <SymbolSelector 
        localPairs={localPairs} 
        selectedSymbol={activeSymbol} 
        onSelect={setActiveSymbol} 
      />

      {activeSymbol && currentPair && (
        <>
          <ResampleForm 
            selectedSymbol={activeSymbol} 
            availableTfs={availableTfs} 
          />

          <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm space-y-4 flex flex-col min-h-[600px]">
            <div className="flex justify-between items-center border-b border-[#30363d] pb-3">
              <h4 className="text-white text-xs font-bold uppercase tracking-wider flex items-center text-[#58a6ff]">
                <i className="fa-solid fa-chart-candlestick mr-2"></i> Graphique Interactif (Optimisé)
              </h4>
              
              <div className="flex items-center space-x-3">
                <button 
                  onClick={() => setIsVisualsModalOpen(true)} 
                  className="px-4 py-1.5 bg-[#0d1117] border border-[#58a6ff] hover:bg-[#1f6feb]/20 text-[#58a6ff] hover:text-white text-[11px] font-bold uppercase rounded-lg transition-colors shadow-sm"
                >
                  <i className="fa-solid fa-layer-group mr-2"></i> Gérer l'Affichage
                </button>
                <div className="flex items-center space-x-3 bg-[#0d1117] border border-[#30363d] rounded-lg px-3 py-1.5">
                  <span className="text-[11px] text-[#8b949e] font-semibold uppercase tracking-wider">Timeframe Maître :</span>
                  <select 
                    value={selectedTf} 
                    onChange={(e) => setSelectedTf(e.target.value)} 
                    className="bg-transparent text-xs text-white focus:outline-none font-mono cursor-pointer font-bold"
                  >
                    {availableTfs.map((tf) => (
                      <option key={tf} value={tf}>{tf}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            <div className="flex-1 w-full bg-[#0d1117] rounded-lg border border-[#30363d] flex items-center justify-center overflow-hidden shadow-inner">
              <OhlcvCanvas 
                traces={traces} 
                layout={layout} 
                isLoading={isLoading} 
              />
            </div>
          </div>

          <VisualConfigModal 
            isOpen={isVisualsModalOpen} 
            onClose={() => setIsVisualsModalOpen(false)} 
            availableTfs={availableTfs} 
          />
        </>
      )}
    </div>
  );
};
