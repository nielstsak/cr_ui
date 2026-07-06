import React, { useState, useEffect } from 'react';
import useAppStore from '../store/useAppStore';

const TALIB_INDICATORS = [
  "AD", "ADOSC", "ADX", "ADXR", "APO", "AROON", "AROONOSC", "ATR", "AVGPRICE", "BBANDS", 
  "BETA", "BOP", "CCI", "CDL2CROWS", "CDL3BLACKCROWS", "CDL3INSIDE", "CDL3LINESTRIKE", 
  "CDL3STARSINSOUTH", "CDL3WHITESOLDIERS", "CDLABANDONEDBABY", "CDLADVANCEBLOCK", 
  "CDLBELTHOLD", "CDLBREAKAWAY", "CDLCLOSINGMARUBOZU", "CDLCONCEALBABYSWALL", 
  "CDLCOUNTERATTACK", "CDLDARKCLOUDCOVER", "CDLDOJI", "CDLDOJISTAR", "CDLDRAGONFLYDOJI", 
  "CDLENGULFING", "CDLEVENINGDOJISTAR", "CDLEVENINGSTAR", "CDLGAPSIDESIDEWHITE", 
  "CDLGRAVESTONEDOJI", "CDLHAMMER", "CDLHANGINGMAN", "CDLHARAMI", "CDLHARAMICROSS", 
  "CDLHIGHWAVE", "CDLHIKKAKE", "CDLHIKKAKEMOD", "CDLHOMINGPIGEON", "CDLIDENTICAL3CROWS", 
  "CDLINNECK", "CDLINVERTEDHAMMER", "CDLKICKING", "CDLKICKINGBYLENGTH", "CDLLADDERBOTTOM", 
  "CDLLONGLEGGEDDOJI", "CDLLONGLINE", "CDLMARUBOZU", "CDLMATCHINGLOW", "CDLMATHOLD", 
  "CDLMORNINGDOJISTAR", "CDLMORNINGSTAR", "CDLONNECK", "CDLPIERCING", "CDLRICKSHAWMAN", 
  "CDLRISEFALL3METHODS", "CDLSEPARATINGLINES", "CDLSHOOTINGSTAR", "CDLSHORTLINE", 
  "CDLSPINNINGTOP", "CDLSTALLEDPATTERN", "CDLSTICKSANDWICH", "CDLTAKURI", "CDLTASUKIGAP", 
  "CDLTHRUSTING", "CDLTRISTAR", "CDLUNIQUE3RIVER", "CDLUPSIDEGAP2CROWS", "CDLXSIDEGAP3METHODS", 
  "CMO", "CORREL", "DEMA", "DX", "EMA", "HT_DCPERIOD", "HT_DCPHASE", "HT_PHASOR", "HT_SINE", 
  "HT_TRENDLINE", "HT_TRENDMODE", "KAMA", "LINEARREG", "LINEARREG_ANGLE", "LINEARREG_INTERCEPT", 
  "LINEARREG_SLOPE", "MA", "MACD", "MACDEXT", "MACDFIX", "MAMA", "MAX", "MAXINDEX", "MEDPRICE", 
  "MFI", "MIDPOINT", "MIDPRICE", "MIN", "MININDEX", "MINMAX", "MINMAXINDEX", "MINUS_DI", 
  "MINUS_DM", "MOM", "NATR", "OBV", "PLUS_DI", "PLUS_DM", "PPO", "ROC", "ROCP", "ROCR", 
  "ROCR100", "RSI", "SAR", "SAREXT", "SMA", "STDDEV", "STOCH", "STOCHF", "STOCHRSI", "SUM", 
  "T3", "TEMA", "TRANGE", "TRIMA", "TRIX", "TSF", "TYPPRICE", "ULTOSC", "VAR", "WCLPRICE", 
  "WILLR", "WMA"
];

export default function IndicatorManager({ selectedSymbol }) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  
  const rawCalculated = useAppStore(state => state.calculatedIndicators)[selectedSymbol];
  const applyIndicators = useAppStore(state => state.applyIndicators);
  const isGlobalLoading = useAppStore(state => state.isLoading);
  
  const [localChecked, setLocalChecked] = useState([]);

  // La synchronisation ne se fait STRICTEMENT qu'à l'ouverture de la modale pour éviter les boucles
  useEffect(() => {
    if (isOpen) {
      setLocalChecked(rawCalculated || []);
    }
  }, [isOpen]); // rawCalculated intentionnellement exclu des dépendances

  const toggleCheck = (ind) => {
    setLocalChecked(prev => prev.includes(ind) ? prev.filter(i => i !== ind) : [...prev, ind]);
  };

  const handleCompute = async () => {
    await applyIndicators(selectedSymbol, localChecked);
    setIsOpen(false);
  };

  const filteredIndicators = TALIB_INDICATORS.filter(ind => ind.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm flex justify-between items-center">
      <div>
        <h3 className="text-white text-sm font-bold uppercase tracking-wider flex items-center">
          <i className="fa-solid fa-database mr-2 text-[#58a6ff]"></i> Indicateurs TA-Lib (Modification Fichiers Data)
        </h3>
        <p className="text-xs text-gray-500 mt-1">Calcule et injecte définitivement les indicateurs choisis dans l'historique HDF5 du symbole.</p>
      </div>
      <button
        onClick={() => setIsOpen(true)}
        disabled={!selectedSymbol || isGlobalLoading}
        className="px-5 py-2 bg-[#161b22] border border-[#58a6ff] hover:bg-[#1f6feb]/20 text-[#58a6ff] hover:text-white text-xs font-bold uppercase rounded-lg transition-colors shadow-sm disabled:opacity-50"
      >
        <i className="fa-solid fa-microchip mr-2"></i> Calculer TA-Lib
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70 backdrop-blur-sm">
          <div className="bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl w-[800px] max-h-[85vh] flex flex-col">
            <div className="flex justify-between items-center p-5 border-b border-[#30363d]">
              <h2 className="text-[#58a6ff] font-bold uppercase tracking-wider text-sm">Base de données : Ajout d'Indicateurs TA-Lib</h2>
              <button onClick={() => setIsOpen(false)} className="text-[#8b949e] hover:text-white"><i className="fa-solid fa-xmark"></i></button>
            </div>
            
            <div className="p-4 border-b border-[#30363d] bg-[#0d1117]">
              <input 
                type="text" 
                placeholder="Rechercher un indicateur (ex: RSI, SMA...)" 
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-[#1f6feb] font-mono"
              />
            </div>

            <div className="flex-1 overflow-y-auto p-5">
              <div className="grid grid-cols-4 gap-4">
                {filteredIndicators.map(ind => (
                  <label key={ind} className="flex items-center space-x-2 text-xs text-[#c9d1d9] cursor-pointer hover:text-white select-none bg-[#0d1117] border border-[#30363d] p-2 rounded">
                    <input 
                      type="checkbox" 
                      checked={localChecked.includes(ind)}
                      onChange={() => toggleCheck(ind)}
                      className="rounded bg-[#161b22] border-[#30363d] text-[#1f6feb] focus:ring-[#1f6feb] cursor-pointer"
                    />
                    <span className="font-mono font-semibold">{ind}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="p-5 border-t border-[#30363d] flex justify-between items-center bg-[#0d1117] rounded-b-xl">
              <span className="text-xs text-gray-500 font-mono">
                {localChecked.length} indicateur(s) sélectionné(s)
              </span>
              <button 
                onClick={handleCompute}
                disabled={isGlobalLoading}
                className="px-6 py-2 bg-[#1f6feb] hover:bg-[#388bfd] text-white text-xs font-bold uppercase tracking-wider rounded-lg transition-colors shadow-sm disabled:opacity-50"
              >
                {isGlobalLoading ? 'Écriture en cours...' : 'Exécuter les calculs'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}