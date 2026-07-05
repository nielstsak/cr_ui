import React, { useMemo } from 'react';
import useAppStore from '../store/useAppStore';

/**
 * Composant InformationsData - Rework complet pour le Bloc 3 (Informations Symbole).
 * Centralise l'affichage de l'arborescence multi-timeframe ainsi que les rapports d'introspection
 * d'ingestion natifs issus directement des commandes vectorbtpro.
 */
const InformationsData = () => {
  const activeSymbol = useAppStore((state) => state.activeSymbol);
  const descStats = useAppStore((state) => state.descStats);
  const vbtInfo = useAppStore((state) => state.vbtInfo);

  const TIMEFRAME_ORDER = ['5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'];

  // Tri déterministe et ordonné des unités de temps locales détectées sur le disque
  const sortedStats = useMemo(() => {
    if (!descStats) return [];
    return Object.entries(descStats).sort((a, b) => {
      return TIMEFRAME_ORDER.indexOf(a[0]) - TIMEFRAME_ORDER.indexOf(b[0]);
    });
  }, [descStats]);

  if (!activeSymbol) {
    return (
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-8 text-center text-[#8b949e] text-sm italic">
        <i className="fa-solid fa-circle-info mr-2 text-[#1f6feb]"></i>
        Veuillez sélectionner un fichier ou un symbole actif dans le Bloc 2 pour charger ses métadonnées.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      
      {/* SECTION 3.A : data.data['symboleselectionne'].info() */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm space-y-3">
        <h4 className="text-white text-xs font-bold uppercase tracking-wider flex items-center border-b border-[#30363d] pb-2 text-[#58a6ff]">
          <i className="fa-solid fa-terminal mr-2 text-[#8b949e]"></i> 
          Introspection : data.data['{activeSymbol}'].info()
        </h4>
        {vbtInfo && vbtInfo.info ? (
          <pre className="bg-[#0d1117] border border-[#30363d] p-4 rounded-lg text-xs font-mono text-emerald-400 overflow-x-auto whitespace-pre-wrap leading-relaxed shadow-inner max-h-[220px] overflow-y-auto">
            {vbtInfo.info}
          </pre>
        ) : (
          <div className="bg-[#0d1117] border border-[#30363d] p-4 rounded-lg text-xs font-mono text-gray-500 italic">
            Aucun log d'introspection structurel renvoyé par vectorbtpro pour l'actif {activeSymbol}.
          </div>
        )}
      </div>

      {/* SECTION 3.B : data.stats() */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm space-y-3">
        <h4 className="text-white text-xs font-bold uppercase tracking-wider flex items-center border-b border-[#30363d] pb-2 text-[#58a6ff]">
          <i className="fa-solid fa-table-list mr-2 text-[#8b949e]"></i> 
          Calcul Analytique : data.stats()
        </h4>
        {vbtInfo && vbtInfo.stats && Object.keys(vbtInfo.stats).length > 0 ? (
          <div className="bg-[#0d1117] border border-[#30363d] rounded-lg overflow-hidden shadow-inner max-h-[350px] overflow-y-auto">
            <table className="w-full text-left text-xs font-mono text-gray-300 border-collapse">
              <thead>
                <tr className="bg-[#161b22] border-b border-[#30363d] text-gray-400 text-[10px] uppercase tracking-wider">
                  <th className="py-2.5 px-4 font-semibold">Métrique Statistique</th>
                  <th className="py-2.5 px-4 font-semibold text-right">Valeur Calculée</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#30363d]">
                {Object.entries(vbtInfo.stats).map(([metric, value]) => (
                  <tr key={metric} className="hover:bg-[#161b22]/40 transition-colors">
                    <td className="py-2.5 px-4 font-medium text-[#8b949e]">{metric}</td>
                    <td className="py-2.5 px-4 text-right text-white font-bold break-all">
                      {typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 6 }) : String(value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-[#0d1117] border border-[#30363d] p-4 rounded-lg text-xs font-mono text-gray-500 italic">
            Aucun tableau d'évaluation de métriques d'allocation trouvé. Exécutez un run complet.
          </div>
        )}
      </div>

      {/* SECTION 3.C : Synthèse Physique Multi-Timeframe (Conservation Intégrale de l'Historique local HDF5) */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-5 shadow-sm space-y-3">
        <h4 className="text-white text-xs font-bold uppercase tracking-wider flex items-center border-b border-[#30363d] pb-2 text-[#58a6ff]">
          <i className="fa-solid fa-chart-pie mr-2 text-[#8b949e]"></i> 
          Synthèse Physique Descriptive Multi-Timeframe (HDF5)
        </h4>
        {sortedStats.length > 0 ? (
          <div className="overflow-x-auto border border-[#30363d] bg-[#0d1117] rounded-lg shadow-inner">
            <table className="w-full text-left text-xs font-mono text-gray-300 border-collapse">
              <thead>
                <tr className="bg-[#161b22] border-b border-[#30363d] text-gray-400 text-[10px] uppercase tracking-wider">
                  <th className="py-3 px-3">TF</th>
                  <th className="py-3 px-3">Klines</th>
                  <th className="py-3 px-3">Début (UTC)</th>
                  <th className="py-3 px-3">Fin (UTC)</th>
                  <th className="py-3 px-3 text-[#2ecc71]">Vert</th>
                  <th className="py-3 px-3 text-[#e74c3c]">Rouge</th>
                  <th className="py-3 px-3">Min Price</th>
                  <th className="py-3 px-3">Max Price</th>
                  <th className="py-3 px-3">Hold Ratio</th>
                  <th className="py-3 px-3 text-right">Ø Volume</th>
                  <th className="py-3 px-3 text-right">Mèche H.</th>
                  <th className="py-3 px-3 text-right">Mèche B.</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#30363d]">
                {sortedStats.map(([tf, stat]) => {
                  const ratioPositive = stat.hold_ratio_pct >= 0;
                  return (
                    <tr key={tf} className="hover:bg-[#161b22]/40 transition-colors">
                      <td className="py-3 px-3 font-bold text-[#58a6ff]">{tf}</td>
                      <td className="py-3 px-3 text-white">{stat.klines.toLocaleString()}</td>
                      <td className="py-3 px-3 text-gray-400 text-[11px] whitespace-nowrap">{stat.start_date}</td>
                      <td className="py-3 px-3 text-gray-400 text-[11px] whitespace-nowrap">{stat.end_date}</td>
                      <td className="py-3 px-3 text-[#2ecc71] font-semibold">{stat.green_count.toLocaleString()}</td>
                      <td className="py-3 px-3 text-[#e74c3c] font-semibold">{stat.red_count.toLocaleString()}</td>
                      <td className="py-3 px-3 text-white">{stat.min_price}</td>
                      <td className="py-3 px-3 text-white">{stat.max_price}</td>
                      <td className={`py-3 px-3 font-bold ${ratioPositive ? 'text-[#2ecc71]' : 'text-[#e74c3c]'}`}>
                        {ratioPositive ? '+' : ''}{stat.hold_ratio_pct}%
                      </td>
                      <td className="py-3 px-3 text-right text-gray-400">{stat.avg_volume.toLocaleString()}</td>
                      <td className="py-3 px-3 text-right text-gray-300">{stat.avg_upper_wick_pct}%</td>
                      <td className="py-3 px-3 text-right text-gray-300">{stat.avg_lower_wick_pct}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-[#0d1117] border border-[#30363d] p-4 rounded-lg text-xs font-mono text-gray-500 italic">
            Aucune granularité temporelle physique n'est instanciée pour {activeSymbol}.
          </div>
        )}
      </div>

    </div>
  );
};

export default InformationsData;