import React from 'react';
import useAppStore from '../store/useAppStore';

const OVERLAYS_OPTIONS = [
  "SMA", "EMA", "BBANDS", "DEMA", "KAMA", "LINEARREG", "MA", "MAMA", "MIDPOINT", 
  "MIDPRICE", "SAR", "SAREXT", "T3", "TEMA", "TRIMA", "TSF", "WMA", "HT_TRENDLINE"
];

const OSCILLATORS_OPTIONS = [
  "RSI", "ATR", "AD", "ADOSC", "ADX", "ADXR", "APO", "AROON", "AROONOSC", "BETA", 
  "BOP", "CCI", "CMO", "CORREL", "DX", "LINEARREG_ANGLE", "LINEARREG_INTERCEPT", 
  "LINEARREG_SLOPE", "MACD", "MACDEXT", "MACDFIX", "MAX", "MAXINDEX", "MEDPRICE", 
  "MFI", "MIN", "MININDEX", "MINMAX", "MINMAXINDEX", "MINUS_DI", "MINUS_DM", "MOM", 
  "NATR", "OBV", "PLUS_DI", "PLUS_DM", "PPO", "ROC", "ROCP", "ROCR", "ROCR100", 
  "STDDEV", "STOCH", "STOCHF", "STOCHRSI", "SUM", "TRANGE", "TRIX", "TYPPRICE", 
  "ULTOSC", "VAR", "WCLPRICE", "WILLR", "HT_DCPERIOD", "HT_DCPHASE", "HT_PHASOR", 
  "HT_SINE", "HT_TRENDMODE"
];

const IndicatorSettingsModal = ({ isOpen, onClose }) => {
  const selectedOverlays = useAppStore(state => state.selectedOverlays);
  const setSelectedOverlays = useAppStore(state => state.setSelectedOverlays);
  const selectedOscillators = useAppStore(state => state.selectedOscillators);
  const setSelectedOscillators = useAppStore(state => state.setSelectedOscillators);

  if (!isOpen) return null;

  const toggleOverlay = (overlay) => {
    if (selectedOverlays.includes(overlay)) {
      setSelectedOverlays(selectedOverlays.filter(o => o !== overlay));
    } else {
      setSelectedOverlays([...selectedOverlays, overlay]);
    }
  };

  const toggleOscillator = (oscillator) => {
    if (selectedOscillators.includes(oscillator)) {
      setSelectedOscillators(selectedOscillators.filter(o => o !== oscillator));
    } else {
      setSelectedOscillators([...selectedOscillators, oscillator]);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60 backdrop-blur-sm">
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg shadow-xl w-[850px] max-h-[85vh] flex flex-col">
        <div className="flex justify-between items-center p-5 border-b border-[#30363d]">
          <h2 className="text-[#58a6ff] font-semibold uppercase tracking-wider">
            <i className="fa-solid fa-sliders mr-2"></i> Configuration Globale des Indicateurs
          </h2>
          <button onClick={onClose} className="text-[#8b949e] hover:text-white transition-colors">
            ✕
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-6 space-y-8">
          <div>
            <h3 className="text-white mb-4 font-medium border-b border-[#30363d] pb-2">
              Indicateurs de Prix (Overlays)
            </h3>
            <div className="grid grid-cols-4 gap-3">
              {OVERLAYS_OPTIONS.map(ind => (
                <label key={ind} className="flex items-center space-x-2 text-sm text-[#c9d1d9] cursor-pointer hover:text-white select-none">
                  <input 
                    type="checkbox" 
                    checked={selectedOverlays.includes(ind)}
                    onChange={() => toggleOverlay(ind)}
                    className="rounded border-[#30363d] bg-[#0d1117] text-[#1f6feb] focus:ring-[#1f6feb]"
                  />
                  <span>{ind}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-white mb-4 font-medium border-b border-[#30363d] pb-2">
              Oscillateurs (Sous-graphes)
            </h3>
            <div className="grid grid-cols-4 gap-3">
              {OSCILLATORS_OPTIONS.map(ind => (
                <label key={ind} className="flex items-center space-x-2 text-sm text-[#c9d1d9] cursor-pointer hover:text-white select-none">
                  <input 
                    type="checkbox" 
                    checked={selectedOscillators.includes(ind)}
                    onChange={() => toggleOscillator(ind)}
                    className="rounded border-[#30363d] bg-[#0d1117] text-[#1f6feb] focus:ring-[#1f6feb]"
                  />
                  <span>{ind}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
        
        <div className="p-4 border-t border-[#30363d] bg-[#0d1117] flex justify-end rounded-b-lg">
          <button 
            onClick={onClose}
            className="px-6 py-2 bg-[#1f6feb] hover:bg-[#388bfd] text-white font-medium rounded transition-colors shadow-sm"
          >
            Appliquer au Graphique & Fermer
          </button>
        </div>
      </div>
    </div>
  );
};

export default IndicatorSettingsModal;