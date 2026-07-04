import React from 'react';
import useAppStore from '../store/useAppStore';

/**
 * Composant InformationsData - Synthèse Statistique Descriptive Multitemporelle.
 * Analyse et affiche l'intégrité géométrique, temporelle et comportementale
 * des bougies stockées localement dans les fichiers HDF5.
 */
const InformationsData = () => {
  const activeSymbol = useAppStore((state) => state.activeSymbol);
  const descStats = useAppStore((state) => state.descStats);

  const TIMEFRAME_ORDER = ['5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'];

  // Tri déterministe des unités de temps selon l'échelle temporelle standard
  const sortedStats = React.useMemo(() => {
    if (!descStats) return [];
    return Object.entries(descStats).sort((a, b) => {
      return TIMEFRAME_ORDER.indexOf(a[0]) - TIMEFRAME_ORDER.indexOf(b[0]);
    });
  }, [descStats]);

  if (!activeSymbol) {
    return (
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 text-center text-[#8b949e] text-xs">
        <i className="fa-solid fa-circle-info mr-2 text-[#58a6ff]"></i>
        Sélectionnez un symbole actif pour afficher ses statistiques descriptives de marché.
      </div>
    );
  }

  if (!descStats || sortedStats.length === 0) {
    return (
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 text-center text-[#8b949e] text-xs">
        <i className="fa-solid fa-triangle-exclamation mr-2 text-yellow-500"></i>
        Aucun historique ou timeframe local détecté sur le disque pour la paire {activeSymbol}.
      </div>
    );
  }

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 space-y-4 shadow-sm">
      <div className="flex justify-between items-center border-b border-[#30363d] pb-3">
        <div className="flex items-center space-x-2.5">
          <div className="bg-brand-600/10 p-2 rounded text-[#58a6ff]">
            <i className="fa-solid fa-chart-pie"></i>
          </div>
          <div>
            <h3 className="text-white text-sm font-semibold uppercase tracking-wider">
              Synthèse Descriptive de Marché
            </h3>
            <p className="text-[11px] text-[#8b949e] font-mono uppercase">
              Données physiques calculées par vectorisation (HDF5) : {activeSymbol}
            </p>
          </div>
        </div>
        <span className="text-[10px] bg-brand-500/10 text-brand-500 border border-brand-500/20 px-2 py-0.5 rounded font-mono font-bold uppercase">
          MTF Engine v1.0
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs font-mono text-gray-300">
          <thead>
            <tr className="border-b border-[#30363d] text-gray-400 text-[10px] uppercase tracking-wider">
              <th className="py-3 px-3">TF</th>
              <th className="py-3 px-3">Klines</th>
              <th className="py-3 px-3 text-left">Début (UTC)</th>
              <th className="py-3 px-3 text-left">Fin (UTC)</th>
              <th className="py-3 px-3 text-[#2ecc71]">Positives (Vert)</th>
              <th className="py-3 px-3 text-[#e74c3c]">Négatives (Rouge)</th>
              <th className="py-3 px-3">Min Price</th>
              <th className="py-3 px-3">Max Price</th>
              <th className="py-3 px-3">Hold Ratio</th>
              <th className="py-3 px-3 text-right">Volume Moyen</th>
              <th className="py-3 px-3 text-right">Ø Mèche Haute</th>
              <th className="py-3 px-3 text-right">Ø Mèche Basse</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#30363d]">
            {sortedStats.map(([tf, stat]) => {
              const ratioPositive = stat.hold_ratio_pct >= 0;
              return (
                <tr key={tf} className="hover:bg-[#0d1117]/30 transition-colors">
                  <td className="py-3 px-3 font-bold text-[#58a6ff]">{tf}</td>
                  <td className="py-3 px-3 text-white">{stat.klines.toLocaleString()}</td>
                  <td className="py-3 px-3 text-gray-400 text-[11px]">{stat.start_date}</td>
                  <td className="py-3 px-3 text-gray-400 text-[11px]">{stat.end_date}</td>
                  <td className="py-3 px-3 text-[#2ecc71] font-semibold">{stat.green_count.toLocaleString()}</td>
                  <td className="py-3 px-3 text-[#e74c3c] font-semibold">{stat.red_count.toLocaleString()}</td>
                  <td className="py-3 px-3 text-white">{stat.min_price}</td>
                  <td className="py-3 px-3 text-white">{stat.max_price}</td>
                  <td className={`py-3 px-3 font-bold ${ratioPositive ? 'text-[#2ecc71]' : 'text-[#e74c3c]'}`}>
                    {ratioPositive ? '+' : ''}{stat.hold_ratio_pct}%
                  </td>
                  <td className="py-3 px-3 text-right text-gray-400">{stat.avg_volume.toLocaleString()}</td>
                  <td className="py-3 px-3 text-right text-[#c9d1d9]">{stat.avg_upper_wick_pct}%</td>
                  <td className="py-3 px-3 text-right text-[#c9d1d9]">{stat.avg_lower_wick_pct}%</td>
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