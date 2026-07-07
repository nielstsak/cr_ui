
// frontend/src/features/IndicatorSettings/VisualConfigModal.jsx
import React, { useEffect, useState, useMemo } from 'react';
import { useMarketStore } from '../../entities/market/store';
import { useIndicatorStore } from '../../entities/indicators/store';

export const VisualConfigModal = ({ isOpen, onClose, availableTfs }) => {
  const activeSymbol = useMarketStore((state) => state.activeSymbol);
  const calculatedIndicators = useIndicatorStore((state) => state.calculatedIndicators)[activeSymbol] || [];
  const displayedIndicators = useIndicatorStore((state) => state.displayedIndicators)[activeSymbol] || {};
  const toggleIndicatorOutput = useIndicatorStore((state) => state.toggleIndicatorOutput);
  const updateIndicatorOutputConfig = useIndicatorStore((state) => state.updateIndicatorOutputConfig);
  const fetchIndicatorMetadataBulk = useIndicatorStore((state) => state.fetchIndicatorMetadataBulk);
  const indicatorMetadata = useIndicatorStore((state) => state.indicatorMetadata);
  const indicatorGroups = useIndicatorStore((state) => state.indicatorGroups);
  const fetchIndicatorGroups = useIndicatorStore((state) => state.fetchIndicatorGroups);

  const [expandedGroups, setExpandedGroups] = useState({});

  useEffect(() => {
    fetchIndicatorGroups();
  }, [fetchIndicatorGroups]);

  useEffect(() => {
    if (isOpen && calculatedIndicators.length > 0) {
      fetchIndicatorMetadataBulk(calculatedIndicators);
    }
  }, [isOpen, calculatedIndicators, fetchIndicatorMetadataBulk]);

  const indToGroupMap = useMemo(() => {
    const mapping = {};
    Object.entries(indicatorGroups).forEach(([groupName, indicators]) => {
      indicators.forEach((ind) => {
        mapping[ind] = groupName;
      });
    });
    return mapping;
  }, [indicatorGroups]);

  const groupedCalculated = useMemo(() => {
    return calculatedIndicators.reduce((acc, ind) => {
      const group = indToGroupMap[ind] || 'Autres (Custom)';
      if (!acc[group]) {
        acc[group] = [];
      }
      acc[group].push(ind);
      return acc;
    }, {});
  }, [calculatedIndicators, indToGroupMap]);

  if (!isOpen) return null;

  const toggleGroup = (group) => {
    setExpandedGroups((prev) => ({ ...prev, [group]: !prev[group] }));
  };

  const getExpectedColumns = (indName) => {
    const meta = indicatorMetadata[indName];
    if (!meta || !meta.outputs) return [indName.toUpperCase()];
    if (meta.outputs.length === 1) return [indName.toUpperCase()];
    return meta.outputs.map((out) => `${indName.toUpperCase()}_${out.toUpperCase()}`);
  };

  const getAutoColor = (index) => {
    const colors = ['#58a6ff', '#e67e22', '#e74c3c', '#9b59b6', '#2ecc71'];
    return colors[index % colors.length];
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-70 backdrop-blur-sm p-4">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex justify-between items-center p-5 border-b border-[#30363d] bg-[#0d1117] rounded-t-xl">
          <h2 className="text-[#58a6ff] font-bold uppercase tracking-wider text-sm">
            <i className="fa-solid fa-layer-group mr-2"></i> Catalogue Visuel des Indicateurs Calculés
          </h2>
          <button onClick={onClose} className="text-[#8b949e] hover:text-white">
            <i className="fa-solid fa-xmark text-lg"></i>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {Object.keys(groupedCalculated).length === 0 ? (
            <div className="text-center py-10 text-gray-500 text-xs italic">
              Aucun indicateur calculé détecté.
            </div>
          ) : (
            Object.entries(groupedCalculated).sort().map(([groupName, inds]) => (
              <div key={groupName} className="border border-[#30363d] rounded-lg overflow-hidden">
                <button
                  onClick={() => toggleGroup(groupName)}
                  className="w-full flex justify-between items-center p-3 bg-[#0d1117] hover:bg-[#1f6feb]/10 transition-colors"
                >
                  <span className="text-[#c9d1d9] font-bold text-xs uppercase tracking-wider">
                    {groupName} <span className="text-[#8b949e] font-normal lowercase ml-2">({inds.length} indicateurs)</span>
                  </span>
                  <i className={`fa-solid fa-chevron-${expandedGroups[groupName] ? 'up' : 'down'} text-[#8b949e]`}></i>
                </button>

                {expandedGroups[groupName] && (
                  <div className="p-4 bg-[#161b22] border-t border-[#30363d] grid grid-cols-1 md:grid-cols-2 gap-4">
                    {inds.map((ind) => {
                      const expectedColumns = getExpectedColumns(ind);
                      const defaultPosition = groupName === 'Overlap Studies' ? 'overlay' : 'subchart';

                      return (
                        <div key={ind} className="bg-[#0d1117] border border-[#30363d] rounded-lg p-4 shadow-inner">
                          <h3 className="text-white font-bold font-mono text-sm border-b border-[#30363d] pb-2 mb-3 text-[#58a6ff]">
                            {ind}
                          </h3>

                          <div className="space-y-4">
                            {availableTfs.map((tf) => (
                              <div key={`${ind}-${tf}`} className="border-l-2 border-[#30363d] pl-3 space-y-2">
                                <h4 className="text-[#8b949e] font-bold text-[10px] uppercase tracking-wider">TF : {tf}</h4>

                                {expectedColumns.map((colName, cIdx) => {
                                  const isDisplayed = !!displayedIndicators[ind]?.[tf]?.[colName];
                                  const config = displayedIndicators[ind]?.[tf]?.[colName] || {};

                                  const defaultConfig = {
                                    color: getAutoColor(cIdx),
                                    position: defaultPosition,
                                    type: colName.includes('HIST') ? 'bar' : 'lines',
                                    width: 1.5,
                                    opacity: 1
                                  };

                                  return (
                                    <div key={colName} className={`p-2 rounded border ${isDisplayed ? 'bg-[#1f6feb]/5 border-[#1f6feb]/30' : 'bg-transparent border-transparent'}`}>
                                      <div className="flex items-center space-x-2">
                                        <input
                                          type="checkbox"
                                          checked={isDisplayed}
                                          onChange={() => toggleIndicatorOutput(activeSymbol, ind, tf, colName, defaultConfig)}
                                          className="rounded bg-[#161b22] border-[#30363d] text-[#1f6feb] cursor-pointer"
                                        />
                                        <span className="text-[11px] font-mono text-[#c9d1d9]">{colName}</span>
                                      </div>

                                      {isDisplayed && (
                                        <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-[#30363d]">
                                          <div>
                                            <select
                                              value={config.position}
                                              onChange={(e) => updateIndicatorOutputConfig(activeSymbol, ind, tf, colName, 'position', e.target.value)}
                                              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-1 py-1 text-[10px] text-white"
                                            >
                                              <option value="overlay">Sur le prix</option>
                                              <option value="subchart">Sous le prix</option>
                                            </select>
                                          </div>
                                          <div className="flex items-center space-x-2">
                                            <input
                                              type="color"
                                              value={config.color}
                                              onChange={(e) => updateIndicatorOutputConfig(activeSymbol, ind, tf, colName, 'color', e.target.value)}
                                              className="w-4 h-4 bg-transparent cursor-pointer rounded"
                                            />
                                            <select
                                              value={config.type}
                                              onChange={(e) => updateIndicatorOutputConfig(activeSymbol, ind, tf, colName, 'type', e.target.value)}
                                              className="flex-1 bg-[#0d1117] border border-[#30363d] rounded px-1 py-1 text-[10px] text-white"
                                            >
                                              <option value="lines">Lignes</option>
                                              <option value="bar">Barres</option>
                                              <option value="markers">Points</option>
                                            </select>
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        <div className="p-4 border-t border-[#30363d] flex justify-end bg-[#0d1117] rounded-b-xl">
          <button onClick={onClose} className="px-6 py-2 bg-[#1f6feb] hover:bg-[#388bfd] text-white text-xs font-bold uppercase rounded-lg shadow-sm transition-colors">
            Fermer le gestionnaire
          </button>
        </div>
      </div>
    </div>
  );
};