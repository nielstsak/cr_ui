# backend/core/ml_optuna_engine.py
import os
import json
import logging
import time
import traceback
from datetime import datetime
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd
import numba
import optuna
import vectorbtpro as vbt

import lightgbm as lgb
import xgboost as xgb

from backend.data.hdf5_storage import HDF5Storage
from backend.api.routes_feature_engineering import timeframe_to_minutes

logger = logging.getLogger("MLOptunaEngine")

@numba.njit
def compute_triple_barrier_labels_jit(opens, highs, lows, target_threshold, sl_ratio, hold_candles):
    n = len(opens)
    labels = np.zeros(n, dtype=np.int32) # 0 = Hold, 1 = Long, 2 = Short
    
    tp_pct = target_threshold / 100.0
    sl_pct = (target_threshold * sl_ratio) / 100.0
    
    for i in range(n - hold_candles - 1):
        entry_price = opens[i + 1]
        
        # Long barriers
        tp_long = entry_price * (1.0 + tp_pct)
        sl_long = entry_price * (1.0 - sl_pct)
        
        # Short barriers
        tp_short = entry_price * (1.0 - tp_pct)
        sl_short = entry_price * (1.0 + sl_pct)
        
        long_hit = 0  # 1 if hit TP, -1 if hit SL
        short_hit = 0 # 1 if hit TP, -1 if hit SL
        long_idx = 999999
        short_idx = 999999
        
        # Check Long
        for j in range(i + 1, i + 1 + hold_candles):
            h = highs[j]
            l = lows[j]
            
            if h >= tp_long and l <= sl_long:
                long_hit = -1
                long_idx = j
                break
            elif h >= tp_long:
                long_hit = 1
                long_idx = j
                break
            elif l <= sl_long:
                long_hit = -1
                long_idx = j
                break
                
        # Check Short
        for j in range(i + 1, i + 1 + hold_candles):
            h = highs[j]
            l = lows[j]
            
            if l <= tp_short and h >= sl_short:
                short_hit = -1
                short_idx = j
                break
            elif l <= tp_short:
                short_hit = 1
                short_idx = j
                break
            elif h >= sl_short:
                short_hit = -1
                short_idx = j
                break
                
        # Final decision
        if long_hit == 1 and (short_hit != 1 or long_idx < short_idx):
            labels[i] = 1
        elif short_hit == 1 and (long_hit != 1 or short_idx < long_idx):
            labels[i] = 2
            
    return labels

def get_annualization_factor(timeframe: str) -> float:
    minutes = timeframe_to_minutes(timeframe)
    return (365.0 * 24.0 * 60.0) / minutes

def get_indicator_group(col_name: str) -> str:
    name = col_name.upper().split('_')[0]
    if name.startswith('CDL'):
        return 'pattern'
    elif name in ['ATR', 'NATR', 'TRANGE']:
        return 'volatility'
    elif name in ['AVGPRICE', 'MEDPRICE', 'TYPPRICE', 'WCLPRICE']:
        return 'price'
    elif name in ['OBV', 'AD', 'ADOSC']:
        return 'volume'
    elif name in ['SMA', 'EMA', 'WMA', 'DEMA', 'TEMA', 'KAMA', 'MA', 'BBANDS', 'SAR', 'MIDPOINT', 'MIDPRICE']:
        return 'overlap'
    else:
        return 'momentum'

# Disable Optuna logging output to avoid cluttering gateway logs
optuna.logging.set_verbosity(optuna.logging.WARNING)

@numba.njit(nogil=True, parallel=False)
def simulate_trading_numba(
    preds: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    threshold_x: float,
    entry_sig_threshold: float,
    direction: int, # 1: Long, -1: Short
    fee_rate: float,
    slippage_rate: float
) -> Tuple[np.ndarray, np.ndarray, int, int]:
    """
    Keep old numba simulator for backward compatibility and test validation.
    """
    n = len(preds)
    equity = 1.0
    equity_curve = np.ones(n, dtype=np.float64)
    trades_count = 0
    wins_count = 0
    returns = np.zeros(n, dtype=np.float64)
    
    for i in range(n):
        pred = preds[i]
        o = opens[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        
        # Long
        if direction == 1:
            if pred >= entry_sig_threshold:
                trades_count += 1
                # Entry price with slippage
                entry_price = o * (1.0 + slippage_rate)
                tp_price = o * (1.0 + threshold_x / 100.0)
                
                # Check TP
                if h >= tp_price:
                    exit_price = tp_price * (1.0 - slippage_rate)
                    wins_count += 1
                else:
                    exit_price = c * (1.0 - slippage_rate)
                
                trade_return = (exit_price - entry_price) / entry_price - fee_rate * 2.0
                returns[i] = trade_return
                equity *= (1.0 + trade_return)
        # Short
        elif direction == -1:
            if pred >= entry_sig_threshold:
                trades_count += 1
                # Entry price with slippage
                entry_price = o * (1.0 - slippage_rate)
                tp_price = o * (1.0 - threshold_x / 100.0)
                
                # Check TP
                if l <= tp_price:
                    exit_price = tp_price * (1.0 + slippage_rate)
                    wins_count += 1
                else:
                    exit_price = c * (1.0 + slippage_rate)
                
                trade_return = (entry_price - exit_price) / entry_price - fee_rate * 2.0
                returns[i] = trade_return
                equity *= (1.0 + trade_return)
                
        equity_curve[i] = equity
    return equity_curve, returns, trades_count, wins_count

@numba.njit(nogil=True, parallel=False)
def calculate_metrics_numba(
    equity_curve: np.ndarray,
    returns: np.ndarray,
    annualization_factor: float
) -> Tuple[float, float, float]:
    """
    Keep old numba metrics for backward compatibility and test validation.
    """
    n = len(returns)
    if n == 0:
        return 0.0, 0.0, 0.0
        
    mean_ret = np.mean(returns)
    std_ret = np.std(returns)
    
    # Sharpe
    if std_ret > 1e-9:
        sharpe = (mean_ret / std_ret) * np.sqrt(annualization_factor)
    else:
        sharpe = 0.0
        
    # Sortino
    downside_returns = returns[returns < 0.0]
    if len(downside_returns) > 0:
        std_downside = np.std(downside_returns)
        if std_downside > 1e-9:
            sortino = (mean_ret / std_downside) * np.sqrt(annualization_factor)
        else:
            sortino = 0.0
    else:
        sortino = 0.0
        
    # Max Drawdown
    max_dd = 0.0
    peak = equity_curve[0]
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd
            
    return sharpe, sortino, max_dd

class MLOptunaEngine:
    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = os.path.abspath(storage_dir)

    def load_and_prepare_data(
        self,
        symbol: str,
        timeframe: str,
        target_threshold: float,
        target_format: str
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Loads base OHLCV and Deepened Features from HDF5 and merges them on open_time.
        Computes targets for both directions (Long/High-Open and Short/Open-Low) shifted by -1.
        Returns (merged_df, feature_cols)
        """
        symbol_clean = symbol.upper().replace("/", "")
        ohlcv_file = os.path.join(self.storage_dir, "BINANCE", symbol_clean, timeframe.lower(), "ohlcv.h5")
        features_file = os.path.join(self.storage_dir, "optuna_features", symbol_clean, f"{timeframe.lower()}.h5")

        if not os.path.exists(ohlcv_file):
            raise FileNotFoundError(f"OHLCV data file not found: {ohlcv_file}")
        if not os.path.exists(features_file):
            raise FileNotFoundError(f"Deepened features file not found: {features_file}. Please run Feature Engineering first.")

        # 1. Load OHLCV
        with HDF5Storage(ohlcv_file, mode='r', group_path="/OHLCV") as st:
            ohlcv_arr = st.read_array(st.dataset_path)
        df_ohlcv = pd.DataFrame(ohlcv_arr)

        # 2. Load Features
        with HDF5Storage(features_file, mode='r', group_path="/features") as st:
            features_arr = st.read_array(st.dataset_path)
        df_feats = pd.DataFrame(features_arr)

        # Identify features
        feature_cols = [c for c in df_feats.columns if c != 'open_time']
        if not feature_cols:
            raise ValueError(f"No features found in {features_file}")

        # 3. Merge on open_time
        df = pd.merge(df_ohlcv, df_feats, on='open_time', how='inner')

        # 4. Compute Wick targets at t+1 (shift -1)
        wick_high = (df['high'] - df['open']) / df['open'] * 100.0
        wick_low = (df['open'] - df['low']) / df['open'] * 100.0

        df['target_wick_long'] = wick_high.shift(-1)
        df['target_wick_short'] = wick_low.shift(-1)

        # Drop any row containing NaNs before calculating windows (important for clean rolling bounds)
        df.dropna(subset=['target_wick_long', 'target_wick_short'] + feature_cols, inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Add datetime index
        df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
        df.sort_values('open_time', inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Define targets
        if target_format == "classification":
            df['target_long'] = (df['target_wick_long'] >= target_threshold).astype(np.int32)
            df['target_short'] = (df['target_wick_short'] >= target_threshold).astype(np.int32)
        elif target_format == "regression":
            df['target_long'] = df['target_wick_long']
            df['target_short'] = df['target_wick_short']
        else:
            raise ValueError(f"Unknown target format: {target_format}")

        # For backward compatibility
        df['target_wick'] = df['target_wick_long']
        df['target'] = df['target_long']

        logger.info(f"Loaded {len(df)} candles with {len(feature_cols)} features for {symbol} {timeframe}")
        return df, feature_cols

    def run_optuna_study(
        self,
        study_id: str,
        config: Dict[str, Any],
        on_trial_complete_cb = None
    ) -> Dict[str, Any]:
        """
        Runs the Optuna Multi-Objective NSGA-II Optimization study using VectorBT Pro portfolio simulation.
        All hyperparameters (timeframe features, target formats, thresholds, algorithms, horizon) are suggested inside the trial.
        """
        symbol = config["symbol"]
        trading_direction = config.get("trading_direction", "both")
        feature_cols = []
        fee_rate = float(config.get("fee_rate", 0.001))
        slippage_rate = float(config.get("slippage_rate", 0.0005))
        leverage = float(config.get("leverage", 1.0))
        n_trials = int(config.get("n_trials", 20))

        # Trial Variable Bounds
        is_len_days_min = int(config.get("is_length_days_min", 15))
        is_len_days_max = int(config.get("is_length_days_max", 90))
        oos_len_hours_min = int(config.get("oos_length_hours_min", 12))
        oos_len_hours_max = int(config.get("oos_length_hours_max", 168))

        lr_min = float(config.get("learning_rate_min", 0.01))
        lr_max = float(config.get("learning_rate_max", 0.3))
        max_depth_min = int(config.get("max_depth_min", 3))
        max_depth_max = int(config.get("max_depth_max", 8))
        colsample_min = float(config.get("colsample_bytree_min", 0.3))
        colsample_max = float(config.get("colsample_bytree_max", 1.0))

        symbol_clean = symbol.upper().replace("/", "")

        # 1. Detect all available timeframes for symbol features
        features_dir = os.path.join(self.storage_dir, "optuna_features", symbol_clean)
        available_tfs = []
        if os.path.exists(features_dir):
            for f in os.listdir(features_dir):
                if f.endswith(".h5"):
                    available_tfs.append(f[:-3].lower())
        if not available_tfs:
            available_tfs = [config["timeframe"].lower()]

        # 2. Load base OHLCV data
        ohlcv_file = os.path.join(self.storage_dir, "BINANCE", symbol_clean, config["timeframe"].lower(), "ohlcv.h5")
        if not os.path.exists(ohlcv_file):
            raise FileNotFoundError(f"OHLCV data file not found: {ohlcv_file}")
            
        with HDF5Storage(ohlcv_file, mode='r', group_path="/OHLCV") as st:
            ohlcv_arr = st.read_array(st.dataset_path)
        df_base = pd.DataFrame(ohlcv_arr)
        df_base['datetime'] = pd.to_datetime(df_base['open_time'], unit='ms')
        df_base = df_base.sort_values('open_time')

        # 3. Pre-load and shift all available timeframes features to prevent look-ahead bias
        all_tf_features = {}
        for tf in available_tfs:
            tf_feat_file = os.path.join(self.storage_dir, "optuna_features", symbol_clean, f"{tf}.h5")
            if os.path.exists(tf_feat_file):
                try:
                    with HDF5Storage(tf_feat_file, mode='r', group_path="/features") as st:
                        arr = st.read_array(st.dataset_path)
                    df_tf = pd.DataFrame(arr)
                    
                    # Align to candle close/end time by adding timeframe duration
                    tf_delta = pd.Timedelta(tf)
                    df_tf['open_time'] = df_tf['open_time'] + int(tf_delta.total_seconds() * 1000)
                    df_tf = df_tf.sort_values('open_time')
                    all_tf_features[tf] = df_tf
                except Exception as e:
                    logger.error(f"Error pre-loading features for timeframe {tf}: {e}")

        trials_records = []

        def objective(trial):
            # 1. Suggest optimized hyperparameters or use fixed configuration values
            target_format = config["target_format"] if "target_format" in config else trial.suggest_categorical("target_format", ["classification", "regression"])
            model_type = config["model_type"] if "model_type" in config else trial.suggest_categorical("model_type", ["lightgbm", "xgboost"])
            metric_type = config["metric_type"] if "metric_type" in config else trial.suggest_categorical("metric_type", ["pnl", "sharpe", "sortino"])
            
            target_threshold = float(config["target_threshold"]) if "target_threshold" in config else trial.suggest_float("target_threshold", 0.5, 3.0)
            # FIX #1: entry_sig_threshold always in [0.1, 0.9] regardless of format or threshold
            if target_format == "classification":
                entry_sig_threshold = float(config["entry_sig_threshold"]) if "entry_sig_threshold" in config else trial.suggest_float("entry_sig_threshold", 0.15, 0.75)
            else:
                # Regression: threshold on predicted % move — bounded to realistic values
                entry_sig_threshold = float(config["entry_sig_threshold"]) if "entry_sig_threshold" in config else trial.suggest_float("entry_sig_threshold", 0.1, 0.9)
                
            hold_candles = int(config["hold_candles"]) if "hold_candles" in config else trial.suggest_int("hold_candles", 2, 48)
            
            # Dynamic multi-timeframe feature selection
            tfs_to_use = []
            for tf in available_tfs:
                if "feature_timeframes" in config:
                    if tf in config["feature_timeframes"]:
                        tfs_to_use.append(tf)
                else:
                    if trial.suggest_categorical(f"use_tf_{tf}", [True, False]):
                        tfs_to_use.append(tf)
            if not tfs_to_use:
                tfs_to_use = [config["timeframe"].lower()]
                
            # Enforce that at least 2 timeframes higher than 5m are selected
            higher_tfs_used = [tf for tf in tfs_to_use if tf != "5m"]
            if len(higher_tfs_used) < 2:
                raise optuna.exceptions.TrialPruned("Must select at least 2 timeframes higher than 5m.")
                
             # Dynamic indicator group selection
            groups_to_use = []
            for g in ["momentum", "overlap", "volume", "volatility", "price"]:
                if "indicator_groups" in config:
                    if g in config["indicator_groups"]:
                        groups_to_use.append(g)
                else:
                    if trial.suggest_categorical(f"use_group_{g}", [True, False]):
                        groups_to_use.append(g)
            if not groups_to_use:
                groups_to_use = ["momentum", "overlap", "volume"]
                
            top_n_features = int(config["top_n_features"]) if "top_n_features" in config else trial.suggest_int("top_n_features", 5, 50)
            
            # Standard training bounds
            is_length_days = trial.suggest_int("is_length_days", is_len_days_min, is_len_days_max)
            # FIX #2: OOS window is NOT suggested by Optuna — it is always 72h (7 fixed folds of 72h = 21 days total)
            oos_length_hours = 72
            learning_rate = trial.suggest_float("learning_rate", lr_min, lr_max, log=True)
            max_depth = trial.suggest_int("max_depth", max_depth_min, max_depth_max)
            colsample_bytree = trial.suggest_float("colsample_bytree", colsample_min, colsample_max)
            
            reg_alpha = trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True)
            reg_lambda = trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True)
            sl_ratio = trial.suggest_float("sl_ratio", 0.2, 1.5)
            
            if model_type == "lightgbm":
                min_child_samples = trial.suggest_int("min_child_samples", 5, 80)
                num_leaves = trial.suggest_int("num_leaves", 7, 63)
            elif model_type == "xgboost":
                min_child_weight = trial.suggest_float("min_child_weight", 0.5, 10.0)

            # 2. Merge features for selected timeframes and groups
            df_trial = df_base.copy()
            feature_cols = []
            
            for tf in tfs_to_use:
                if tf in all_tf_features:
                    df_tf = all_tf_features[tf]
                    cols_filtered = ['open_time']
                    for col in df_tf.columns:
                        if col == 'open_time':
                            continue
                        if get_indicator_group(col) in groups_to_use:
                            cols_filtered.append(col)
                    if len(cols_filtered) > 1:
                        df_tf_filtered = df_tf[cols_filtered]
                        df_trial = pd.merge_asof(df_trial, df_tf_filtered, on='open_time', direction='backward')
                        feature_cols.extend([c for c in cols_filtered if c != 'open_time'])

            if not feature_cols:
                raise optuna.exceptions.TrialPruned("No indicators selected for this group/timeframe combo.")

            # 3. Dynamic target computation based on prediction horizon (hold_candles)
            if target_format == "classification":
                opens = df_trial['open'].values
                highs = df_trial['high'].values
                lows = df_trial['low'].values
                labels = compute_triple_barrier_labels_jit(opens, highs, lows, target_threshold, sl_ratio, hold_candles)
                df_trial['target_multiclass'] = labels
                df_trial['target_long'] = (labels == 1).astype(np.int32)
                df_trial['target_short'] = (labels == 2).astype(np.int32)
                df_trial['target'] = labels
                df_trial['target_wick'] = (labels == 1).astype(np.float32)
                df_trial.dropna(subset=feature_cols, inplace=True)
                df_trial.reset_index(drop=True, inplace=True)
            else:
                h = hold_candles
                df_trial['target_wick_long'] = ((df_trial['high'].rolling(window=h).max().shift(-h) - df_trial['open'].shift(-1)) / df_trial['open'].shift(-1)) * 100.0
                df_trial['target_wick_short'] = ((df_trial['open'].shift(-1) - df_trial['low'].rolling(window=h).min().shift(-h)) / df_trial['open'].shift(-1)) * 100.0
                df_trial.dropna(subset=['target_wick_long', 'target_wick_short'] + feature_cols, inplace=True)
                df_trial.reset_index(drop=True, inplace=True)
                df_trial['target_long'] = df_trial['target_wick_long']
                df_trial['target_short'] = df_trial['target_wick_short']
                df_trial['target'] = df_trial['target_long']
                df_trial['target_wick'] = df_trial['target_wick_long']
            
            if len(df_trial) < 100:
                raise optuna.exceptions.TrialPruned("Not enough data rows after merging and target computation.")

            # 4. Pearson correlation-based feature selection
            if len(feature_cols) > top_n_features:
                corrs = []
                for col in feature_cols:
                    c_long = abs(df_trial[col].corr(df_trial['target_long']))
                    c_short = abs(df_trial[col].corr(df_trial['target_short']))
                    max_c = max(c_long, c_short)
                    if not np.isnan(max_c):
                        corrs.append((col, max_c))
                corrs.sort(key=lambda x: x[1], reverse=True)
                feature_cols = [x[0] for x in corrs[:top_n_features]]

            df = df_trial

            # Dynamic number of folds to cover exactly 21 days (504 hours) of OOS data
            t_start = df['datetime'].min()
            t_end = df['datetime'].max()
            is_delta = pd.Timedelta(days=is_length_days)
            oos_delta = pd.Timedelta(hours=oos_length_hours)
            n_oos_folds = int(np.ceil(504.0 / oos_length_hours))

            windows = []
            curr_oos_end = t_end

            for _ in range(n_oos_folds):
                curr_oos_start = curr_oos_end - oos_delta
                curr_is_end = curr_oos_start
                curr_is_start = curr_is_end - is_delta

                if curr_is_start < t_start:
                    break

                windows.append((curr_is_start, curr_is_end, curr_oos_start, curr_oos_end))
                curr_oos_end = curr_oos_start

            # Sort windows chronologically (oldest fold first)
            windows = sorted(windows, key=lambda w: w[0])

            if len(windows) == 0:
                raise optuna.exceptions.TrialPruned("Not enough data to form even one IS/OOS window.")

            # Arrays to collect OOS predictions and target candles
            oos_preds_long = []
            oos_preds_short = []
            oos_opens = []
            oos_highs = []
            oos_lows = []
            oos_closes = []
            oos_times = []

            # 3. WFO loop
            for win_idx, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
                df_is = df[(df['datetime'] >= is_start) & (df['datetime'] < is_end)]
                df_oos = df[(df['datetime'] >= oos_start) & (df['datetime'] < oos_end)]

                if len(df_is) < 10 or len(df_oos) == 0:
                    continue

                split_idx = int(len(df_is) * 0.8)
                df_train = df_is.iloc[:split_idx]
                df_val = df_is.iloc[split_idx:]

                X_train = df_train[feature_cols].values
                X_val = df_val[feature_cols].values
                X_oos = df_oos[feature_cols].values

                # Train/predict model
                preds_long = np.zeros(len(df_oos))
                preds_short = np.zeros(len(df_oos))
                
                if target_format == "classification":
                    y_train = df_train['target_multiclass'].values
                    y_val = df_val['target_multiclass'].values
                    
                    if len(np.unique(y_train)) < 2 or len(np.unique(y_val)) < 2:
                        raise optuna.exceptions.TrialPruned("Multiclass target has less than 2 classes in train or val split.")
                        
                    if model_type == "lightgbm":
                        model = lgb.LGBMClassifier(
                            objective="multiclass",
                            num_class=3,
                            learning_rate=learning_rate,
                            max_depth=max_depth,
                            num_leaves=min(num_leaves, 2**max_depth - 1),
                            colsample_bytree=colsample_bytree,
                            reg_alpha=reg_alpha,
                            reg_lambda=reg_lambda,
                            min_child_samples=min_child_samples,
                            n_estimators=500,
                            random_state=42,
                            n_jobs=1,
                            verbosity=-1
                        )
                        model.fit(
                            X_train, y_train,
                            eval_set=[(X_val, y_val)],
                            callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)]
                        )
                        probs = model.predict_proba(X_oos)
                        probs_full = np.zeros((len(df_oos), 3))
                        for idx, c in enumerate(model.classes_):
                            if c in [0, 1, 2]:
                                probs_full[:, int(c)] = probs[:, idx]
                        if trading_direction in ["both", "long"]:
                            preds_long = probs_full[:, 1]
                        if trading_direction in ["both", "short"]:
                            preds_short = probs_full[:, 2]
                    else:  # xgboost
                        model = xgb.XGBClassifier(
                            objective="multi:softprob",
                            num_class=3,
                            learning_rate=learning_rate,
                            max_depth=max_depth,
                            colsample_bytree=colsample_bytree,
                            reg_alpha=reg_alpha,
                            reg_lambda=reg_lambda,
                            min_child_weight=min_child_weight,
                            n_estimators=500,
                            random_state=42,
                            n_jobs=1,
                            early_stopping_rounds=30,
                            eval_metric="mlogloss"
                        )
                        model.fit(
                            X_train, y_train,
                            eval_set=[(X_val, y_val)],
                            verbose=False
                        )
                        probs = model.predict_proba(X_oos)
                        probs_full = np.zeros((len(df_oos), 3))
                        for idx, c in enumerate(model.classes_):
                            if c in [0, 1, 2]:
                                probs_full[:, int(c)] = probs[:, idx]
                        if trading_direction in ["both", "long"]:
                            preds_long = probs_full[:, 1]
                        if trading_direction in ["both", "short"]:
                            preds_short = probs_full[:, 2]
                else:
                    # Keep independent regression models
                    if trading_direction in ["both", "long"]:
                        y_train_long = df_train['target_long'].values
                        y_val_long = df_val['target_long'].values
                        if model_type == "lightgbm":
                            model_long = lgb.LGBMRegressor(
                                learning_rate=learning_rate,
                                max_depth=max_depth,
                                num_leaves=min(num_leaves, 2**max_depth - 1),
                                colsample_bytree=colsample_bytree,
                                reg_alpha=reg_alpha,
                                reg_lambda=reg_lambda,
                                min_child_samples=min_child_samples,
                                n_estimators=500,
                                random_state=42,
                                n_jobs=1,
                                verbosity=-1
                            )
                            model_long.fit(
                                X_train, y_train_long,
                                eval_set=[(X_val, y_val_long)],
                                callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)]
                            )
                            preds_long = model_long.predict(X_oos)
                        elif model_type == "xgboost":
                            model_long = xgb.XGBRegressor(
                                learning_rate=learning_rate,
                                max_depth=max_depth,
                                colsample_bytree=colsample_bytree,
                                reg_alpha=reg_alpha,
                                reg_lambda=reg_lambda,
                                min_child_weight=min_child_weight,
                                n_estimators=500,
                                random_state=42,
                                n_jobs=1,
                                early_stopping_rounds=30,
                                eval_metric="rmse"
                            )
                            model_long.fit(
                                X_train, y_train_long,
                                eval_set=[(X_val, y_val_long)],
                                verbose=False
                            )
                            preds_long = model_long.predict(X_oos)

                    if trading_direction in ["both", "short"]:
                        y_train_short = df_train['target_short'].values
                        y_val_short = df_val['target_short'].values
                        if model_type == "lightgbm":
                            model_short = lgb.LGBMRegressor(
                                learning_rate=learning_rate,
                                max_depth=max_depth,
                                num_leaves=min(num_leaves, 2**max_depth - 1),
                                colsample_bytree=colsample_bytree,
                                reg_alpha=reg_alpha,
                                reg_lambda=reg_lambda,
                                min_child_samples=min_child_samples,
                                n_estimators=500,
                                random_state=42,
                                n_jobs=1,
                                verbosity=-1
                            )
                            model_short.fit(
                                X_train, y_train_short,
                                eval_set=[(X_val, y_val_short)],
                                callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)]
                            )
                            preds_short = model_short.predict(X_oos)
                        elif model_type == "xgboost":
                            model_short = xgb.XGBRegressor(
                                learning_rate=learning_rate,
                                max_depth=max_depth,
                                colsample_bytree=colsample_bytree,
                                reg_alpha=reg_alpha,
                                reg_lambda=reg_lambda,
                                min_child_weight=min_child_weight,
                                n_estimators=500,
                                random_state=42,
                                n_jobs=1,
                                early_stopping_rounds=30,
                                eval_metric="rmse"
                            )
                            model_short.fit(
                                X_train, y_train_short,
                                eval_set=[(X_val, y_val_short)],
                                verbose=False
                            )
                            preds_short = model_short.predict(X_oos)

                # Filter valid next-candle indices
                next_indices = df_oos.index + 1
                valid_mask = next_indices < len(df)
                if not np.any(valid_mask):
                    continue

                valid_next_indices = next_indices[valid_mask]

                preds_long_filtered = preds_long[valid_mask]
                preds_short_filtered = preds_short[valid_mask]
                next_candles = df.iloc[valid_next_indices]
                
                oos_preds_long.extend(preds_long_filtered.tolist())
                oos_preds_short.extend(preds_short_filtered.tolist())
                oos_opens.extend(next_candles['open'].values.tolist())
                oos_highs.extend(next_candles['high'].values.tolist())
                oos_lows.extend(next_candles['low'].values.tolist())
                oos_closes.extend(next_candles['close'].values.tolist())
                oos_times.extend(next_candles['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S').values.tolist())

            if len(oos_preds_long) == 0:
                trial_summary = {
                    "trial_number": trial.number,
                    "params": trial.params,
                    "values": [0.0, 0.0],
                    "state": "COMPLETE",
                    "metrics": {
                        "sharpe": 0.0,
                        "sortino": 0.0,
                        "max_drawdown": 1.0,
                        "trades_count": 0,
                        "wins_count": 0,
                        "win_rate": 0.0,
                        "final_equity": 1.0
                    },
                    "equity_curve": [1.0],
                    "timestamps": []
                }
                trials_records.append(trial_summary)
                return 0.0, 0.0

            # 4. Continuous VectorBT Pro portfolio simulation
            sim_index = pd.to_datetime(oos_times)
            close_s = pd.Series(oos_closes, index=sim_index)
            open_s = pd.Series(oos_opens, index=sim_index)
            high_s = pd.Series(oos_highs, index=sim_index)
            low_s = pd.Series(oos_lows, index=sim_index)

            pred_long_s = pd.Series(oos_preds_long, index=sim_index)
            pred_short_s = pd.Series(oos_preds_short, index=sim_index)

            if target_format == "classification":
                if trading_direction == "both":
                    long_entries = (pred_long_s >= entry_sig_threshold) & (pred_long_s > pred_short_s)
                    short_entries = (pred_short_s >= entry_sig_threshold) & (pred_short_s > pred_long_s)
                else:
                    long_entries = pred_long_s >= entry_sig_threshold
                    short_entries = pred_short_s >= entry_sig_threshold
            else:
                if trading_direction == "both":
                    long_entries = (pred_long_s >= target_threshold) & (pred_long_s > pred_short_s)
                    short_entries = (pred_short_s >= target_threshold) & (pred_short_s > pred_long_s)
                else:
                    long_entries = pred_long_s >= target_threshold
                    short_entries = pred_short_s >= target_threshold

            long_exits = long_entries.shift(hold_candles, fill_value=False)
            short_exits = short_entries.shift(hold_candles, fill_value=False)

            sl_stop = target_threshold * sl_ratio / 100.0

            pf = vbt.Portfolio.from_signals(
                close=close_s,
                open=open_s,
                high=high_s,
                low=low_s,
                long_entries=long_entries,
                long_exits=long_exits,
                short_entries=short_entries,
                short_exits=short_exits,
                price=open_s,
                tp_stop=target_threshold / 100.0,
                sl_stop=sl_stop,
                leverage=leverage,
                fees=fee_rate,
                slippage=slippage_rate,
                init_cash=100.0
            )

            # Calculate metrics
            total_return = float(pf.total_return)
            sharpe = float(pf.sharpe_ratio)
            if np.isnan(sharpe) or np.isinf(sharpe):
                sharpe = 0.0
            sortino = float(pf.sortino_ratio)
            if np.isnan(sortino) or np.isinf(sortino):
                sortino = 0.0
            max_dd = float(pf.max_drawdown)
            if np.isnan(max_dd) or np.isinf(max_dd):
                max_dd = 0.0

            trades_count = int(pf.trades.count())
            wins_count = int(pf.trades.winning.count())
            win_rate = float(pf.trades.win_rate) if trades_count > 0 else 0.0
            final_equity = float(pf.final_value)
            equity_curve = pf.value

            primary_metric = total_return if metric_type == "pnl" else (sortino if metric_type == "sortino" else sharpe)

            trial_summary = {
                "trial_number": trial.number,
                "params": trial.params,
                "values": [primary_metric, max_dd],
                "state": "COMPLETE",
                "metrics": {
                    "sharpe": float(sharpe),
                    "sortino": float(sortino),
                    "max_drawdown": float(max_dd),
                    "trades_count": int(trades_count),
                    "wins_count": int(wins_count),
                    "win_rate": float(win_rate),
                    "final_equity": float(final_equity)
                },
                "equity_curve": equity_curve.tolist(),
                "timestamps": oos_times
            }
            trials_records.append(trial_summary)

            return primary_metric, -float(trades_count)

        # FIX #3: Remove fixed seed so each study explores independently
        study = optuna.create_study(
            study_name=study_id,
            directions=["maximize", "minimize"],
            sampler=optuna.samplers.NSGAIISampler(seed=None)
        )

        logger.info(f"Starting Optuna Study {study_id} with {n_trials} trials...")
        
        import joblib
        chunk_size = 12
        num_chunks = int(np.ceil(n_trials / chunk_size))
        interrupted = False
        
        for chunk_idx in range(num_chunks):
            current_chunk_trials = min(chunk_size, n_trials - chunk_idx * chunk_size)
            try:
                # Use threading backend for parallel workers sharing process memory safely
                with joblib.parallel_backend("threading", n_jobs=current_chunk_trials):
                    study.optimize(objective, n_trials=current_chunk_trials, catch=(Exception,))
            except Exception as e:
                logger.error(f"Error in chunk {chunk_idx}: {e}")
                
            completed = min((chunk_idx + 1) * chunk_size, n_trials)
            if on_trial_complete_cb:
                progress_pct = completed / n_trials * 100.0
                on_trial_complete_cb(completed, progress_pct, trials_records)
                
            # REACTIVE EARLY STOPPING check (evaluate after 36 completed trials)
            if completed >= 36:
                completed_complete_trials = [t for t in trials_records if t["state"] == "COMPLETE"]
                if len(completed_complete_trials) > 0:
                    best_pnl_so_far = max([t["metrics"].get("final_equity", 100.0) - 100.0 for t in completed_complete_trials])
                    max_trades = max([t["metrics"].get("trades_count", 0) for t in completed_complete_trials])
                    
                    # If best PnL is still very negative (< -10%) or we have executed no trades, prune early
                    if best_pnl_so_far < -10.0 or max_trades < 2:
                        logger.warning(f"Reactive Early Stopping: Study {study_id} interrupted early due to poor results (Best PnL: {best_pnl_so_far:.2f}%, Max Trades: {max_trades})")
                        interrupted = True
                        break

        # Study complete or interrupted! Identify Pareto front
        pareto_trials = study.best_trials
        pareto_numbers = [t.number for t in pareto_trials]
        
        # Final results payload
        results = {
            "study_id": study_id,
            "created_at": datetime.now().isoformat(),
            "config": config,
            "status": "interrupted" if interrupted else "completed",
            "progress": 100.0,
            "feature_cols": feature_cols,
            "trials": trials_records,
            "pareto_front": pareto_numbers
        }

        # Save to disk
        dest_dir = os.path.join(self.storage_dir, "optuna_studies")
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = os.path.join(dest_dir, f"{study_id}.json")
        with open(dest_file, "w") as f:
            json.dump(results, f, indent=4)

        logger.info(f"Optuna Study {study_id} completed successfully. Saved to {dest_file}")
        return results
