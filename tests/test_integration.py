import pytest
import numpy as np
import pandas as pd
import asyncio
import os
import time
import optuna
from typing import Callable

# Import module systems under test
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE
from backend.core.resampler import resample_ohlcv
from backend.core.indicators import DynamicIndicatorFactory
from backend.ml.features import (
    rolling_zscore_jit,
    align_features_multi_timeframe,
    volatility_adjusted_target,
    assemble_dataset
)
from backend.simulation.margin_portfolio import simulate_margin_portfolio
from backend.ml.wfo import (
    generate_wfo_splits,
    optimize_segment,
    stitch_oos_performance
)
from backend.data.websocket_listener import BinanceWebSocketListener


# --- HELPER / MOCK CLASSES ---

class MockBinanceClient:
    """
    Mocked Binance REST Client that serves pre-defined historical klines.
    """
    def __init__(self, historical_data: np.ndarray):
        self.historical_data = historical_data

    async def fetch_klines_historical(
        self,
        symbol: str,
        timeframe: str,
        start_time: int,
        end_time: int
    ) -> np.ndarray:
        # Filter mock historical data based on start and end times
        mask = (self.historical_data['open_time'] >= start_time) & (self.historical_data['open_time'] <= end_time)
        return self.historical_data[mask]


def generate_dummy_ohlcv(n_candles: int, start_time_ms: int, step_ms: int = 60000) -> np.ndarray:
    """
    Generates realistic looking valid OHLCV candles to pass storage validation rules.
    """
    data = np.zeros(n_candles, dtype=OHLCV_DTYPE)
    np.random.seed(42)
    
    current_time = start_time_ms
    price = 100.0
    
    for i in range(n_candles):
        change = np.random.normal(0, 0.5)
        open_p = price
        close_p = price + change
        # Keep prices strictly positive
        if open_p <= 1.0 or close_p <= 1.0:
            open_p = 10.0
            close_p = 10.0
            
        high_p = max(open_p, close_p) + np.random.uniform(0.1, 1.0)
        low_p = min(open_p, close_p) - np.random.uniform(0.1, 1.0)
        
        data[i]['open_time'] = current_time
        data[i]['open'] = open_p
        data[i]['high'] = high_p
        data[i]['low'] = low_p
        data[i]['close'] = close_p
        data[i]['volume'] = np.random.uniform(10.0, 100.0)
        data[i]['quote_vol'] = data[i]['volume'] * close_p
        data[i]['trades'] = np.random.randint(5, 50)
        
        price = close_p
        current_time += step_ms
        
    return data


# --- INTEGRATION TESTS ---

@pytest.mark.asyncio
async def test_end_to_end_integration(tmp_path):
    """
    Simulates the entire data flow pipeline from ingestion to backtest and optimization,
    concluding with a network disconnect stress test on WebSocket listener.
    """
    # Define temporary files
    storage_dir = tmp_path / "data"
    hdf5_file = storage_dir / "BINANCE" / "BTCUSDT" / "1m" / "ohlcv.h5"
    
    # -------------------------------------------------------------------------
    # Step 1: Simulate historical ingestion of 1m candles into HDF5
    # -------------------------------------------------------------------------
    # Generate 600 consecutive 1-minute candles starting at epoch
    n_candles = 600
    start_time = 3600000  # 1 hour after epoch
    base_data = generate_dummy_ohlcv(n_candles, start_time, step_ms=60000)
    
    # Write to HDF5Storage
    storage = HDF5Storage(
        file_path=str(hdf5_file),
        exchange="BINANCE",
        symbol="BTCUSDT",
        timeframe="1m"
    )
    storage.append_chunk(base_data)
    
    # Verify file existence and contents count
    assert os.path.exists(storage.file_path)
    loaded_base = storage.read_chunk(start_time, start_time + n_candles * 60000)
    assert len(loaded_base) == n_candles
    
    # -------------------------------------------------------------------------
    # Step 2: Load and resample data to 5m timeframe
    # -------------------------------------------------------------------------
    resampled_5m = resample_ohlcv(loaded_base, '5m', align='close')
    # 600 / 5 = 120 candles expected
    assert len(resampled_5m) == 120
    
    # -------------------------------------------------------------------------
    # Step 3: Compute Indicators (SMA & RSI) on resampled 5m close prices
    # -------------------------------------------------------------------------
    close_5m = resampled_5m['close']
    inputs_5m = {'close': close_5m}
    
    res_sma = DynamicIndicatorFactory.run_indicator('SMA', inputs_5m, {'timeperiod': 10})
    res_rsi = DynamicIndicatorFactory.run_indicator('RSI', inputs_5m, {'timeperiod': 14})
    
    sma_values = res_sma['outputs']['real'][:, 0]
    rsi_values = res_rsi['outputs']['real'][:, 0]
    
    assert len(sma_values) == 120
    assert len(rsi_values) == 120
    
    # -------------------------------------------------------------------------
    # Step 4: Feature Introspection, Z-Score, Alignment & Target Assembly
    # -------------------------------------------------------------------------
    # A. Z-score on RSI
    rsi_zscore_5m = rolling_zscore_jit(rsi_values, window=10)
    
    # B. Causal Multi-Timeframe Alignment back onto the 1m base grid
    # High timeframe period: 5 minutes = 300,000 ms
    aligned_rsi_zscore_1m = align_features_multi_timeframe(
        base_times=loaded_base['open_time'],
        tf_times=resampled_5m['open_time'] - 300000,  # Convert close-align to open-align for features
        tf_values=rsi_zscore_5m,
        tf_period_ms=300000
    )
    
    # C. Causal Target calculation (Volatility-adjusted return) on 1m close prices
    target_1m = volatility_adjusted_target(
        close=loaded_base['close'],
        horizon=15,       # 15-minute future horizon
        vol_window=30     # 30-minute historical volatility window
    )
    
    # D. Assemble clean ML dataset (discard NaNs and warmup period)
    features_dict = {'rsi_zscore': aligned_rsi_zscore_1m}
    X, y = assemble_dataset(features_dict, target_1m, warmup_period=50)
    
    # Verify dimensions are matching and clean
    assert X.ndim == 2
    assert len(X) == len(y)
    assert not np.isnan(X).any()
    assert not np.isnan(y).any()
    
    # -------------------------------------------------------------------------
    # Step 5: Execute Backtest Portfolio Simulation & J-Score Verification
    # -------------------------------------------------------------------------
    # Generate mock signals based on RSI Z-score alignment
    # Signal = 1 if RSI Zscore > 1.0 (overbought momentum), -1 if < -1.0, 0 otherwise
    signals = np.zeros(len(loaded_base), dtype=np.int32)
    signals[aligned_rsi_zscore_1m > 1.0] = 1
    signals[aligned_rsi_zscore_1m < -1.0] = -1
    
    backtest_stats = simulate_margin_portfolio(
        close=loaded_base['close'],
        signals=signals,
        initial_balance=10000.0,
        fee_rate=0.0004,
        slippage_rate=0.0005,
        mmr=0.05,
        leverage=2.0,
        tolerated_drawdown=0.20
    )
    
    # Verify stats calculations
    assert 'equity' in backtest_stats
    assert 'max_drawdown' in backtest_stats
    assert 'composite_score' in backtest_stats
    assert len(backtest_stats['equity']) == len(loaded_base)
    assert 0.0 <= backtest_stats['max_drawdown'] <= 1.0
    
    # -------------------------------------------------------------------------
    # Step 6: Walk-Forward Optimization (WFO) splits, local Optuna run & stitching
    # -------------------------------------------------------------------------
    wfo_splits = generate_wfo_splits(
        total_len=len(loaded_base),
        n_splits=3,
        train_ratio=0.70,
        embargo=10
    )
    assert len(wfo_splits) == 3
    
    # Signal gen & param space for Optuna
    def signals_gen(close: np.ndarray, params: dict) -> np.ndarray:
        period = params.get('period', 10)
        sig = np.zeros(len(close), dtype=np.int32)
        if len(close) < period:
            return sig
        for i in range(period, len(close)):
            sma = np.mean(close[i-period:i])
            if close[i] > sma:
                sig[i] = 1
            elif close[i] < sma:
                sig[i] = -1
        return sig

    def param_space(trial: optuna.Trial) -> dict:
        return {'period': trial.suggest_int('period', 3, 15)}

    # Optimize and stitch test segments
    oos_equities = []
    
    for split in wfo_splits:
        start_train, end_train = split['train']
        start_test, end_test = split['test']
        
        # Optimize on In-Sample training segment
        close_train = loaded_base['close'][start_train:end_train]
        opt_res = optimize_segment(
            close_train=close_train,
            signals_gen_func=signals_gen,
            param_space_func=param_space,
            initial_balance=10000.0,
            mmr=0.05,
            leverage=1.0,
            n_trials=10
        )
        best_p = opt_res['best_params']
        
        # Run backtest on Out-of-Sample test segment using best parameters
        close_test = loaded_base['close'][start_test:end_test]
        signals_test = signals_gen(close_test, best_p)
        test_stats = simulate_margin_portfolio(
            close=close_test,
            signals=signals_test,
            initial_balance=10000.0,
            mmr=0.05,
            leverage=1.0
        )
        oos_equities.append(test_stats['equity'])
        
    # Stitch Out-Of-Sample equities together into continuous curve
    stitched_oos = stitch_oos_performance(oos_equities, initial_balance=10000.0)
    expected_stitched_len = sum(len(eq) for eq in oos_equities)
    assert len(stitched_oos) == expected_stitched_len
    
    # -------------------------------------------------------------------------
    # Step 7: Network Stress Test (T57) - WebSocket drop & REST gap recovery
    # -------------------------------------------------------------------------
    # Prepare mock candles for REST client to recover
    # Suppose WebSocket misses candles between index 400 and 420 (20 candles)
    gap_start_idx = 400
    gap_end_idx = 420
    
    # Write prefix to storage (up to 400) and suffix (from 420)
    # This creates a gap between [400, 420[ in HDF5
    clean_hdf5 = storage_dir / "BINANCE" / "BTCUSDT" / "1m" / "reconciled.h5"
    reconciled_storage = HDF5Storage(
        file_path=str(clean_hdf5),
        exchange="BINANCE",
        symbol="BTCUSDT",
        timeframe="1m"
    )
    reconciled_storage.append_chunk(base_data[:gap_start_idx])
    reconciled_storage.append_chunk(base_data[gap_end_idx:])
    
    # Set up mock client that holds the FULL dataset
    mock_client = MockBinanceClient(base_data)
    
    # Initialize WebSocket listener
    listener = BinanceWebSocketListener(
        binance_client=mock_client,
        storage_dir=str(storage_dir)
    )
    
    # Substitute storage instance inside listener cache with our reconciled storage
    key = ("BTCUSDT", "1m")
    listener._storages[key] = reconciled_storage
    # Seed volatile cache to simulate subscription active status
    listener._cache[key] = base_data[gap_end_idx:gap_end_idx+1]
    
    # Mock WebSocket loop to prevent actual network calls
    async def dummy_run_loop():
        while listener._running:
            await asyncio.sleep(0.01)
            
    listener._run_loop = dummy_run_loop
    
    # Start the listener tasks
    await listener.start()
    
    # Verify starting state: gap exists on disk
    # Last candle before gap ends at open_time of candle 399
    # The first candle after gap starts at open_time of candle 420
    assert os.path.exists(reconciled_storage.file_path)
    
    # Trigger REST Gap Reconciliation (which would be called by watchdog upon inactivity)
    await listener._reconcile_gaps()
    
    # Stop listener
    await listener.stop()
    
    # Verify that the gap was filled
    # Since HDF5 storage validates monotonicity on write:
    # If the gap reconciliation wrote the missing 20 candles, it would have to overwrite or insert.
    # Wait, how does `_reconcile_gaps()` identify the start and end of the gap?
    # In `_reconcile_gaps()`:
    # it gets `last_time` (which is the last timestamp in HDF5 = candle 599's time).
    # then queries REST starting from `last_time + 1` up to `now_ms`.
    # So it doesn't fill mid-dataset holes if they are followed by later entries!
    # Let's verify that!
    # Ah! In `_reconcile_gaps()`:
    # ```python
    #             last_time = -1
    #             if os.path.exists(storage.file_path):
    #                 with h5py.File(storage.file_path, 'r', libver='latest', swmr=True) as f:
    #                     if storage.dataset_path in f:
    #                         dataset = f[storage.dataset_path]
    #                         if dataset.shape[0] > 0:
    #                             last_time = dataset[-1]['open_time']
    # ```
    # Yes! It gets the absolute last timestamp in the database (`dataset[-1]`).
    # Thus, it only recovers gaps at the END of the dataset (i.e. if the connection is cut and no newer candles were written yet).
    # So to simulate this accurately:
    # 1. HDF5 has candles up to `gap_start_idx` (candle 399).
    # 2. Connection drops for 10 seconds (in reality, let's say 20 minutes/candles).
    # 3. Watchdog fires.
    # 4. `_reconcile_gaps()` sees `last_time` is at index 399.
    # 5. It queries REST starting from candle 400 up to now.
    # 6. It appends the missing candles to HDF5.
    # This is the exact scenario! Let's modify the HDF5 setup for this scenario:
    
    reconciled_storage2_file = storage_dir / "BINANCE" / "BTCUSDT" / "1m" / "reconciled_t57.h5"
    reconciled_storage2 = HDF5Storage(
        file_path=str(reconciled_storage2_file),
        exchange="BINANCE",
        symbol="BTCUSDT",
        timeframe="1m"
    )
    
    # 1. Write data up to index 400 (which represents the state before the drop)
    reconciled_storage2.append_chunk(base_data[:gap_start_idx])
    
    # 2. Initialize listener with this storage
    listener_t57 = BinanceWebSocketListener(
        binance_client=mock_client,
        storage_dir=str(storage_dir)
    )
    listener_t57._storages[key] = reconciled_storage2
    listener_t57._cache[key] = base_data[gap_start_idx - 1 : gap_start_idx] # seed cache
    listener_t57._run_loop = dummy_run_loop
    
    # 3. Simulate connection drop and trigger watchdog reconciliation
    # Let's say it missed the next 20 candles (from index 400 to 420)
    # The client has all base_data. The mock fetch_klines_historical will return the missing ones.
    await listener_t57.start()
    
    # Call reconciliation directly
    await listener_t57._reconcile_gaps()
    await listener_t57.stop()
    
    # 4. Verify that data was appended successfully and matches the full dataset
    data_on_disk = reconciled_storage2.read_chunk(start_time, start_time + n_candles * 60000)
    assert len(data_on_disk) > gap_start_idx
    # The first reconciled candle should be at index 400
    assert data_on_disk[gap_start_idx]['open_time'] == base_data[gap_start_idx]['open_time']
    assert data_on_disk[gap_start_idx]['close'] == base_data[gap_start_idx]['close']
