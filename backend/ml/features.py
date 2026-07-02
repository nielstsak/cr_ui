from typing import Dict, Tuple
import numba
import numpy as np


@numba.njit(nogil=True, parallel=False)
def rolling_zscore_jit(x: np.ndarray, window: int, clip_val: float = 4.0) -> np.ndarray:
    """
    Computes a strictly causal rolling Z-score.
    
    For each index t, the mean and standard deviation are computed exclusively
    on the lookback window [t - window, t - 1] to prevent any look-ahead bias.
    Cautions null variances by mapping Z-scores to 0.0. Clips extreme values.
    
    Args:
        x: Input contiguous 1D array of values.
        window: Lookback window size.
        clip_val: Limit threshold to clip outliers.
        
    Returns:
        A 1D array of Z-scores, with NaNs on the first 'window' indices.
    """
    n = len(x)
    out = np.empty(n, dtype=np.float64)
    
    for t in range(n):
        if t < window:
            out[t] = np.nan
            continue
            
        # Calculate mean on the lookback window
        s = 0.0
        for k in range(t - window, t):
            s += x[k]
        mean = s / window
        
        # Calculate standard deviation
        var = 0.0
        for k in range(t - window, t):
            diff = x[k] - mean
            var += diff * diff
        std = np.sqrt(var / window)
        
        if std == 0.0:
            z = 0.0
        else:
            z = (x[t] - mean) / std
            
        # Clip outliers
        if z > clip_val:
            z = clip_val
        elif z < -clip_val:
            z = -clip_val
            
        out[t] = z
        
    return out


@numba.njit(nogil=True, parallel=False)
def align_features_multi_timeframe_jit(
    base_times: np.ndarray,
    tf_times: np.ndarray,
    tf_values: np.ndarray,
    tf_period_ms: int
) -> np.ndarray:
    """
    Core JIT loop for aligning higher timeframe features onto a base timeframe.
    Ensures strict causal alignment: a value is only propagated once its higher
    timeframe candle is fully closed (tf_open_time + tf_period_ms <= base_time).
    """
    n_base = len(base_times)
    n_tf = len(tf_times)
    out = np.empty(n_base, dtype=np.float64)
    
    idx_tf = 0
    last_val = np.nan
    
    for i in range(n_base):
        t_base = base_times[i]
        # Advance through the higher timeframe values while the candle is closed
        while idx_tf < n_tf and tf_times[idx_tf] + tf_period_ms <= t_base:
            last_val = tf_values[idx_tf]
            idx_tf += 1
        out[i] = last_val
        
    return out


def align_features_multi_timeframe(
    base_times: np.ndarray,
    tf_times: np.ndarray,
    tf_values: np.ndarray,
    tf_period_ms: int
) -> np.ndarray:
    """
    Wrapper for multi-timeframe feature alignment.
    
    Args:
        base_times: 1D array of base timestamps (int64) in ms.
        tf_times: 1D array of higher timeframe candle open timestamps (int64) in ms.
        tf_values: 1D array of higher timeframe feature values.
        tf_period_ms: Duration of the higher timeframe candle in ms.
        
    Returns:
        Aligned 1D array on the base timeframe grid.
    """
    return align_features_multi_timeframe_jit(
        base_times.astype(np.int64),
        tf_times.astype(np.int64),
        tf_values.astype(np.float64),
        int(tf_period_ms)
    )


@numba.njit(nogil=True, parallel=False)
def volatility_adjusted_target_jit(
    close: np.ndarray,
    horizon: int,
    vol_window: int
) -> np.ndarray:
    """
    Calculates volatility-adjusted log returns target: y_t = log_return(t, t+horizon) / rolling_vol(t).
    Uses strict causal log returns volatility window ending at t.
    
    Args:
        close: 1D array of close prices.
        horizon: Prediction log-return horizon in indices.
        vol_window: Rolling window size for calculating past log-returns standard deviation.
        
    Returns:
        A 1D array of volatility-adjusted returns, with NaNs on bounds.
    """
    n = len(close)
    out = np.empty(n, dtype=np.float64)
    
    # Pre-calculate 1-period log returns
    log_ret = np.empty(n, dtype=np.float64)
    log_ret[0] = 0.0
    for i in range(1, n):
        log_ret[i] = np.log(close[i]) - np.log(close[i - 1])
        
    for t in range(n):
        if t + horizon >= n:
            out[t] = np.nan
            continue
            
        if t < vol_window:
            out[t] = np.nan
            continue
            
        # Standard deviation on log_ret[t - vol_window + 1 : t + 1] (inclusive of t)
        s = 0.0
        for k in range(t - vol_window + 1, t + 1):
            s += log_ret[k]
        mean = s / vol_window
        
        var = 0.0
        for k in range(t - vol_window + 1, t + 1):
            diff = log_ret[k] - mean
            var += diff * diff
        std = np.sqrt(var / vol_window)
        
        if std == 0.0:
            out[t] = 0.0
        else:
            future_ret = np.log(close[t + horizon]) - np.log(close[t])
            out[t] = future_ret / std
            
    return out


def volatility_adjusted_target(
    close: np.ndarray,
    horizon: int,
    vol_window: int
) -> np.ndarray:
    """
    Wrapper for volatility-adjusted target calculation.
    """
    return volatility_adjusted_target_jit(
        close.astype(np.float64),
        int(horizon),
        int(vol_window)
    )


def assemble_dataset(
    features: Dict[str, np.ndarray],
    target: np.ndarray,
    warmup_period: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Assembles a feature matrix X and target vector y from input dictionaries.
    Strips the initial warmup indices containing rolling NaNs and filters out remaining NaNs.
    
    Args:
        features: Dictionary mapping feature names to contiguous 1D arrays of size N.
        target: 1D target array of size N.
        warmup_period: Warmup index period to discard.
        
    Returns:
        A tuple (X, y) of clean matrices ready for ML training.
    """
    feature_names = sorted(features.keys())
    n_rows = len(target)
    n_feats = len(feature_names)
    
    # Construct 2D feature matrix
    X = np.empty((n_rows, n_feats), dtype=np.float64)
    for idx, name in enumerate(feature_names):
        X[:, idx] = features[name]
        
    # Crop warmup period
    X_clean = X[warmup_period:]
    y_clean = target[warmup_period:]
    
    # Construct validation mask to strip any remaining NaNs (e.g. from future horizon)
    valid_mask = ~np.isnan(y_clean)
    
    # Filter features for NaNs
    feat_nan = np.isnan(X_clean).any(axis=1)
    valid_mask = valid_mask & (~feat_nan)
    
    return X_clean[valid_mask], y_clean[valid_mask]
