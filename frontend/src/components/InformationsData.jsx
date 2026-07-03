import React from 'react';
import useAppStore from '../store/useAppStore';

/**
 * Composant d'analyse statistique descriptive vectorielle (T47).
 * Affiche l'intégrité temporelle et géométrique de la paire sélectionnée sur disque.
 */
const InformationsData = () => {
  const { activeSymbol, descStats } = useAppStore();

  const TIMEFRAME_ORDER = ['5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'];

  // Trier les unités de temps selon l'ordre logique
  const sortedStats = React.useMemo(() => {
    if (!descStats) return [];
    return Object.entries(descStats).sort((a, b) => {
      return TIMEFRAME_ORDER.indexOf(a[0]) - TIMEFRAME_ORDER.indexOf(b[0]);
    });
  }, [descStats]);

  if (!activeSymbol) {
    return (
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-6 text-center text-[#8b949e] text-xs">
        Sélectionnez un symbole local de paires de trading pour analyser ses statistiques descriptives.
      </div>
    );
  }

  if (!descStats || sortedStats.length === 0) {
    return (
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-6 text-center text-[#8b949e] text-xs">
        <i className="fa-solid fa-triangle-exclamation mr-2 text-yellow-500"></i>
        Aucune donnée ou unité de temps disponible localement sur le disque pour {activeSymbol}.
      </div>
    );
  }

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 space-y-4 shadow-sm">
      <div className="flex justify-between items-center border-b border-[#30363d] pb-2.5">
        <h3 className="text-white text-xs font-bold uppercase tracking-wider flex items-center">
          <i className="fa-solid fa-chart-pie mr-2 text-[#58a6ff]"></i>
          Analyse Descriptive &amp; Intégrité Temporelle : {activeSymbol}
        </h3>
        <span className="text-[10px] bg-[#1f6feb]/10 text-[#1f6feb] border border-[#1f6feb]/20 font-mono px-2 py-0.5 rounded uppercase font-semibold">
          MTF Vectorial Analysis
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs font-mono text-gray-300">
          <thead>
            <tr className="border-b border-[#30363d] text-gray-400 text-[10px] uppercase">
              <th className="py-2.5 px-3">TF</th>
              <th className="py-2.5 px-3">Bougies</th>
              <th className="py-2.5 px-3">Horodatage Début (UTC)</th>
              <th className="py-2.5 px-3">Horodatage Fin (UTC)</th>
              <th className="py-2.5 px-3 text-[#2ecc71]">Klines Vertes (+)</th>
              <th className="py-2.5 px-3 text-[#e74c3c]">Klines Rouges (-)</th>
              <th className="py-2.5 px-3">Prix Min</th>
              <th className="py-2.5 px-3">Prix Max</th>
              <th className="py-2.5 px-3">Hold Ratio</th>
              <th className="py-2.5 px-3">Ø Vol. Transaction</th>
              <th className="py-2.5 px-3">Ø Mèche Haute</th>
              <th className="py-2.5 px-3">Ø Mèche Basse</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#30363d]">
            {sortedStats.map(([tf, s]) => {
              const holdRatioPositive = s.hold_ratio_pct >= 0;
              return (
                <tr key={tf} className="hover:bg-[#0d1117]/40 transition-colors text-xs">
                  <td className="py-3 px-3 font-bold text-[#58a6ff]">{tf}</td>
                  <td className="py-3 px-3 text-white">{s.klines.toLocaleString()}</td>
                  <td className="py-3 px-3 text-gray-400 text-[11px]">{s.start_date}</td>
                  <td className="py-3 px-3 text-gray-400 text-[11px]">{s.end_date}</td>
                  <td className="py-3 px-3 text-[#2ecc71] font-semibold">
                    {s.green_count.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 text-[#e74c3c] font-semibold">
                    {s.red_count.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 text-white font-semibold">{s.min_price}</td>
                  <td className="py-3 px-3 text-white font-semibold">{s.max_price}</td>
                  <td className={`py-3 px-3 font-bold ${
                    holdRatioPositive ? 'text-[#2ecc71]' : 'text-[#e74c3c]'
                  }`}>
                    {holdRatioPositive ? '+' : ''}{s.hold_ratio_pct}%
                  </td>
                  <td className="py-3 px-3">{s.avg_volume.toLocaleString()}</td>
                  <td className="py-3 px-3 text-[#c9d1d9]">{s.avg_upper_wick_pct}%</td>
                  <td className="py-3 px-3 text-[#c9d1d9]">{s.avg_lower_wick_pct}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default InformationsData;