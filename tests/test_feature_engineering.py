import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from pathlib import Path

from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE
from backend.api.routes_feature_engineering import (
    timeframe_to_minutes,
    get_column_name,
    _deepen_features_coro
)

def test_timeframe_to_minutes():
    assert timeframe_to_minutes("5m") == 5
    assert timeframe_to_minutes("30m") == 30
    assert timeframe_to_minutes("2h") == 120
    assert timeframe_to_minutes("1d") == 1440
    assert timeframe_to_minutes("1w") == 10080
    
    with pytest.raises(ValueError):
        timeframe_to_minutes("invalid")
    with pytest.raises(ValueError):
        timeframe_to_minutes("5")

def test_get_column_name():
    # SMA has a single output 'real' -> should omit it and show 'w20'
    col_sma = get_column_name("SMA", "5m", "real", {"timeperiod": 20})
    assert col_sma == "SMA_5m_w20"
    
    # BBANDS has multiple outputs -> should include upperband and matype/w overrides
    col_bb = get_column_name("BBANDS", "15m", "upperband", {"timeperiod": 20, "matype": 0})
    assert col_bb == "BBANDS_15m_upperband_matype0_w20"
    
    # MACD has multiple outputs -> should include output and fast/slow/sig overrides
    col_macd = get_column_name(
        "MACD", 
        "1h", 
        "macdhist", 
        {"fastperiod": 12, "slowperiod": 26, "signalperiod": 9}
    )
    assert col_macd == "MACD_1h_macdhist_fast12_sig9_slow26"

@pytest.fixture
def mock_multi_tf_env(tmp_path: Path):
    storage_dir = tmp_path / "data"
    
    # Define TFs and sizes
    tfs = ["5m", "30m", "2h"]
    np.random.seed(42)
    
    for tf in tfs:
        symbol_dir = storage_dir / "BINANCE" / "BTCUSDT" / tf
        symbol_dir.mkdir(parents=True, exist_ok=True)
        file_path = symbol_dir / "ohlcv.h5"
        
        # Write 200 candles
        mock_data = np.zeros(200, dtype=OHLCV_DTYPE)
        # Incremental timestamps
        tf_mins = timeframe_to_minutes(tf)
        mock_data['open_time'] = np.arange(1000, 1000 + 200 * tf_mins * 60000, tf_mins * 60000, dtype=np.int64)
        mock_data['open'] = np.random.uniform(50000, 51000, 200)
        mock_data['high'] = mock_data['open'] + 50.0
        mock_data['low'] = mock_data['open'] - 50.0
        mock_data['close'] = mock_data['open'] + np.random.uniform(-10, 10, 200)
        mock_data['volume'] = np.random.uniform(10, 100, 200)
        
        with HDF5Storage(file_path, group_path="/OHLCV", mode='w') as storage:
            storage.write_array(storage.dataset_path, mock_data)
            
    return str(storage_dir)

@patch('backend.api.gateway.app_state')
@patch('backend.api.gateway.tasks_db')
def test_deepen_features_coroutine(mock_tasks_db, mock_app_state, mock_multi_tf_env):
    storage_dir = mock_multi_tf_env
    
    # Setup mocks
    mock_app_state.state = {
        "configurations": {
            "storage_dir": storage_dir
        }
    }
    
    task_id = "test-task-123"
    mock_tasks_db[task_id] = {"status": "running", "progress": 0.0}
    
    # Mock request
    from backend.api.routes_feature_engineering import FeatureDeepenRequest
    req = FeatureDeepenRequest(
        symbol="BTCUSDT",
        indicator_types=["Overlap Studies"] # SMA is in this group
    )
    
    # Run coroutine synchronously
    import asyncio
    asyncio.run(_deepen_features_coro(task_id, req))
    
    # Verify Optuna features folder creation
    optuna_dir = Path(storage_dir) / "optuna_features" / "BTCUSDT"
    assert optuna_dir.exists()
    
    # 5m TF should have ratios of 6 with 30m
    # Expected: SMA_5m_w20, SMA_5m_w40, SMA_5m_w60, SMA_5m_w80, SMA_5m_w100, SMA_5m_w120
    file_5m = optuna_dir / "5m.h5"
    assert file_5m.exists()
    
    with HDF5Storage(file_5m, mode='r', group_path="/features") as storage:
        arr_5m = storage.read_array(storage.dataset_path)
        fields_5m = arr_5m.dtype.names
        assert "open_time" in fields_5m
        assert "SMA_5m_w20" in fields_5m
        assert "SMA_5m_w40" in fields_5m
        assert "SMA_5m_w60" in fields_5m
        assert "SMA_5m_w80" in fields_5m
        assert "SMA_5m_w100" in fields_5m
        assert "SMA_5m_w120" in fields_5m
        # length matches base length
        assert len(arr_5m) == 200
        
    # 30m TF should have ratios of 4 with 2h
    # Expected: SMA_30m_w20, SMA_30m_w40, SMA_30m_w60, SMA_30m_w80
    file_30m = optuna_dir / "30m.h5"
    assert file_30m.exists()
    
    with HDF5Storage(file_30m, mode='r', group_path="/features") as storage:
        arr_30m = storage.read_array(storage.dataset_path)
        fields_30m = arr_30m.dtype.names
        assert "open_time" in fields_30m
        assert "SMA_30m_w20" in fields_30m
        assert "SMA_30m_w40" in fields_30m
        assert "SMA_30m_w60" in fields_30m
        assert "SMA_30m_w80" in fields_30m
        # 100/120 should NOT be in 30m
        assert "SMA_30m_w100" not in fields_30m
        
    # 2h TF has no next TF -> only default w20
    file_2h = optuna_dir / "2h.h5"
    assert file_2h.exists()
    
    with HDF5Storage(file_2h, mode='r', group_path="/features") as storage:
        arr_2h = storage.read_array(storage.dataset_path)
        fields_2h = arr_2h.dtype.names
        assert "open_time" in fields_2h
        assert "SMA_2h_w20" in fields_2h
        assert "SMA_2h_w40" not in fields_2h
