# FICHIER : backend/core/resampler.py
import re
import numba
import numpy as np

# Importation du type de données structuré OHLCV pour la compatibilité HDF5
from backend.data.hdf5_storage import OHLCV_DTYPE

# Dictionnaire de conversion strict des échelles temporelles (Timeframes) en millisecondes
TIMEFRAME_TO_MS = {
    '5m': 300000,
    '15m': 900000,
    '30m': 1800000,
    '1h': 3600000,
    '2h': 7200000,
    '4h': 14400000,
    '6h': 21600000,
    '8h': 28800000,
    '12h': 43200000,
    '1d': 86400000,
}


def timeframe_to_ms(timeframe: str) -> int:
    """
    Parse et convertit une chaîne timeframe (ex: '15m', '4h', '1d') en millisecondes.
    
    Args:
        timeframe: La chaîne de caractères du timeframe à convertir.
        
    Returns:
        La valeur équivalente en millisecondes.
        
    Raises:
        ValueError: Si le format du timeframe est invalide ou non supporté.
    """
    tf = timeframe.lower().strip()
    if tf in TIMEFRAME_TO_MS:
        return TIMEFRAME_TO_MS[tf]
        
    match = re.match(r"^(\d+)([smhdw])$", tf)
    if not match:
        raise ValueError(
            f"Format de timeframe non supporté ou invalide : '{timeframe}'. "
            f"Formats attendus : '5m', '1h', '1d', etc."
        )
        
    value = int(match.group(1))
    unit = match.group(2)
    
    unit_map = {
        's': 1000,
        'm': 60000,
        'h': 3600000,
        'd': 86400000,
        'w': 604800000
    }
    return value * unit_map[unit]


@numba.njit(nogil=True, parallel=False)
def resample_ohlcv_jit(
    in_open_time: np.ndarray,
    in_open: np.ndarray,
    in_high: np.ndarray,
    in_low: np.ndarray,
    in_close: np.ndarray,
    in_volume: np.ndarray,
    in_quote_vol: np.ndarray,
    in_trades: np.ndarray,
    out_open_time: np.ndarray,
    out_open: np.ndarray,
    out_high: np.ndarray,
    out_low: np.ndarray,
    out_close: np.ndarray,
    out_volume: np.ndarray,
    out_quote_vol: np.ndarray,
    out_trades: np.ndarray,
    start_time: int,
    target_timeframe_ms: int,
    align_close: bool
) -> None:
    """
    Boucle de rééchantillonnage compilée JIT optimisée pour exécution parallèle ou thread-safe.
    Gère la propagation des prix sur les trous de marché (gaps) et l'agrégation de volume.
    """
    n_in = len(in_open_time)
    n_out = len(out_open_time)
    
    i = 0  
    last_close = 0.0
    if n_in > 0:
        last_close = in_close[0]
        
    for j in range(n_out):
        p_start = start_time + j * target_timeframe_ms
        p_end = p_start + target_timeframe_ms
        
        has_data = False
        open_val = 0.0
        high_val = -1.0
        low_val = -1.0
        close_val = 0.0
        volume_val = 0.0
        quote_vol_val = 0.0
        trades_val = 0
        
        # Agrégation des données dans la fenêtre temporelle cible
        while i < n_in and in_open_time[i] < p_end:
            t = in_open_time[i]
            if t >= p_start:
                if not has_data:
                    open_val = in_open[i]
                    high_val = in_high[i]
                    low_val = in_low[i]
                    has_data = True
                else:
                    if in_high[i] > high_val:
                        high_val = in_high[i]
                    if in_low[i] < low_val:
                        low_val = in_low[i]
                        
                close_val = in_close[i]
                volume_val += in_volume[i]
                quote_vol_val += in_quote_vol[i]
                trades_val += in_trades[i]
            i += 1
            
        if has_data:
            out_open[j] = open_val
            out_high[j] = high_val
            out_low[j] = low_val
            out_close[j] = close_val
            out_volume[j] = volume_val
            out_quote_vol[j] = quote_vol_val
            out_trades[j] = trades_val
            last_close = close_val
        else:
            # Remplissage par défaut en cas de trou de marché (forward fill)
            out_open[j] = last_close
            out_high[j] = last_close
            out_low[j] = last_close
            out_close[j] = last_close
            out_volume[j] = 0.0
            out_quote_vol[j] = 0.0
            out_trades[j] = 0
            
        if align_close:
            out_open_time[j] = p_end
        else:
            out_open_time[j] = p_start


def resample_ohlcv(data: np.ndarray, target_timeframe: str, align: str = 'close') -> np.ndarray:
    """
    Rééchantillonne des données OHLCV brutes vers une unité de temps supérieure cible.
    
    Args:
        data: Tableau structuré numpy de type OHLCV_DTYPE.
        target_timeframe: Timeframe cible (ex: '15m', '4h', '1d').
        align: Type d'alignement temporel ('open' ou 'close').
        
    Returns:
        Un tableau numpy structuré contenant les bougies rééchantillonnées.
    """
    if not isinstance(data, np.ndarray):
        raise TypeError("Les données sources doivent être sous forme de tableau NumPy.")
    if data.dtype != OHLCV_DTYPE:
        raise ValueError("Le format de données doit correspondre au type structuré OHLCV strict.")
    if len(data) == 0:
        return np.empty(0, dtype=OHLCV_DTYPE)
        
    align_close = align.lower().strip() == 'close'
    target_ms = timeframe_to_ms(target_timeframe)
    
    if len(data) > 1:
        source_ms = data['open_time'][1] - data['open_time'][0]
        if target_ms < source_ms:
            raise ValueError(
                f"Le timeframe cible '{target_timeframe}' ({target_ms}ms) doit être strictement "
                f"supérieur au timeframe source ({source_ms}ms)."
            )
            
    first_time = data['open_time'][0]
    last_time = data['open_time'][-1]
    
    start_t = (first_time // target_ms) * target_ms
    end_t = (last_time // target_ms) * target_ms
    
    total_periods = int((end_t - start_t) // target_ms) + 1
    out_data = np.empty(total_periods, dtype=OHLCV_DTYPE)
    
    resample_ohlcv_jit(
        data['open_time'], data['open'], data['high'], data['low'], data['close'], data['volume'], data['quote_vol'], data['trades'],
        out_data['open_time'], out_data['open'], out_data['high'], out_data['low'], out_data['close'], out_data['volume'], out_data['quote_vol'], out_data['trades'],
        start_t, target_ms, align_close
    )
    
    return out_data