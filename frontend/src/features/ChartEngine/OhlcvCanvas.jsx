
import React from 'react';
import Plot from 'react-plotly.js';

export const OhlcvCanvas = ({ traces, layout, isLoading, error }) => {
  if (isLoading) {
    return (
      <div className="text-[#8b949e] flex flex-col items-center justify-center py-20 bg-[#0d1117] rounded-lg border border-[#30363d] h-[500px]">
        <i className="fa-solid fa-circle-notch fa-spin fa-2x mb-3 text-[#1f6feb]"></i>
        <span className="text-xs font-mono">Chargement des données du graphique...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-[#f85149] text-xs font-mono bg-[#f85149]/10 p-4 rounded border border-[#f85149]/20 h-[500px] flex items-center justify-center">
        <div>
          <i className="fa-solid fa-triangle-exclamation mr-2"></i>
          {error}
        </div>
      </div>
    );
  }

  if (!traces || traces.length === 0) {
    return (
      <div className="text-[#8b949e] text-xs italic py-20 bg-[#0d1117] rounded-lg border border-[#30363d] h-[500px] flex items-center justify-center">
        Aucune série temporelle disponible.
      </div>
    );
  }

  return (
    <div className="w-full bg-[#0d1117] rounded-lg border border-[#30363d] overflow-hidden shadow-inner p-2" style={{ height: layout?.height ? `${layout.height}px` : '500px' }}>
      <Plot
        data={traces}
        layout={layout}
        useResizeHandler={true}
        style={{ width: '100%', height: '100%' }}
        config={{ responsive: true, displayModeBar: true, scrollZoom: true }}
      />
    </div>
  );
};