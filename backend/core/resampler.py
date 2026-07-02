import re
import numba
import numpy as np

# Import strict OHLCV dtype
from backend.data.hdf5_storage import OHLCV_DTYPE

# Pre-defined timeframe conversions to milliseconds
TIMEFRAME_TO_MS = {
    '1s': 1000,
    '1m': 60000,
    '3m': 180000,
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
    '1w': 604800000
}


def timeframe_to_ms(timeframe: str) -> int:
    """
    Parses a timeframe string (e.g., '1m', '5m', '1h', '2d') into milliseconds.
    Raises ValueError if format is invalid or unsupported.
    """
    tf = timeframe.lower().strip()
    if tf in TIMEFRAME_TO_MS:
        return TIMEFRAME_TO_MS[tf]
        
    # Matches a digit sequence followed by 's', 'm', 'h', 'd', or 'w'
    match = re.match(r"^(\d+)([smhdw])$", tf)
    if not match:
        raise ValueError(
            f"Unsupported or invalid timeframe format: '{timeframe}'. "
            f"Expected format like '15s', '5m', '4h', '1d', etc."
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
    in_open_time, in_open, in_high, in_low, in_close, in_volume, in_quote_vol, in_trades,
    out_open_time, out_open, out_high, out_low, out_close, out_volume, out_quote_vol, out_trades,
    start_time, target_timeframe_ms, align_close
):
    """
    Strict JIT compiled resampling loop.
    Maps fine-grained input candles to pre-allocated coarser target arrays.
    Handles gaps using forward-fill on prices and zero-fill on volumes.
    """
    n_in = len(in_open_time)
    n_out = len(out_open_time)
    
    i = 0  # Sequential search index for source candles
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
        
        # Sift through contiguous sorted source candles falling within [p_start, p_end[
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
            # Market gap: propagate last close and reset counters
            out_open[j] = last_close
            out_high[j] = last_close
            out_low[j] = last_close
            out_close[j] = last_close
            out_volume[j] = 0.0
            out_quote_vol[j] = 0.0
            out_trades[j] = 0
            
        # Causal Alignment to avoid look-ahead bias
        if align_close:
            out_open_time[j] = p_end
        else:
            out_open_time[j] = p_start


def resample_ohlcv(data: np.ndarray, target_timeframe: str, align: str = 'close') -> np.ndarray:
    """
    Public wrapper function for JIT resampling.
    
    Args:
        data: A C-contiguous NumPy structured array with OHLCV_DTYPE.
        target_timeframe: Timeframe code (e.g. '5m', '1h', '1d').
        align: 'close' for causal alignment to Close Time (prevents look-ahead bias),
               'open' for alignment to Open Time.
               
    Returns:
        A resampled structured NumPy array matching OHLCV_DTYPE.
    """
    if not isinstance(data, np.ndarray):
        raise TypeError("Input data must be a NumPy array.")
    if data.dtype != OHLCV_DTYPE:
        raise ValueError(f"Input array must match strict OHLCV_DTYPE: {OHLCV_DTYPE}.")
    if len(data) == 0:
        return np.empty(0, dtype=OHLCV_DTYPE)
        
    align_close = align.lower().strip() == 'close'
    target_ms = timeframe_to_ms(target_timeframe)
    
    # Check that target timeframe is indeed larger than source timeframe (implied by first two timestamps)
    if len(data) > 1:
        source_ms = data['open_time'][1] - data['open_time'][0]
        if target_ms < source_ms:
            raise ValueError(
                f"Target timeframe '{target_timeframe}' ({target_ms}ms) is smaller than "
                f"source data timeframe ({source_ms}ms)."
            )
            
    # Calculate bounds and sizes to pre-allocate output array (prevents memory allocation in JIT loops)
    first_time = data['open_time'][0]
    last_time = data['open_time'][-1]
    
    start_t = (first_time // target_ms) * target_ms
    end_t = (last_time // target_ms) * target_ms
    
    total_periods = int((end_t - start_t) // target_ms) + 1
    
    # Pre-allocate output structured array
    out_data = np.empty(total_periods, dtype=OHLCV_DTYPE)
    
    # Call JIT compiler loop passing contiguous memory column views
    resample_ohlcv_jit(
        data['open_time'], data['open'], data['high'], data['low'], data['close'], data['volume'], data['quote_vol'], data['trades'],
        out_data['open_time'], out_data['open'], out_data['high'], out_data['low'], out_data['close'], out_data['volume'], out_data['quote_vol'], out_data['trades'],
        start_t, target_ms, align_close
    )
    
    return out_data
