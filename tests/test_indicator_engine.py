import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from pathlib import Path
from backend.core.indicator_engine import auto_compute_features
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE

@pytest.fixture
def mock_hdf5_env(tmp_path: Path):
    storage_dir = tmp_path / "data"
    symbol_dir = storage_dir / "BINANCE" / "BTCUSDT" / "1m"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    file_path = symbol_dir / "ohlcv.h5"
    
    mock_data = np.zeros(10, dtype=OHLCV_DTYPE)
    mock_data['open_time'] = np.arange(1000, 11000, 1000, dtype=np.int64)
    mock_data['close'] = np.random.uniform(10, 20, 10)
    
    with HDF5Storage(file_path, group_path="/OHLCV", mode='w') as storage:
        storage.write_array(storage.dataset_path, mock_data)
        
    return str(storage_dir), str(file_path)

@patch('vectorbtpro.Data.from_data')
@patch('talib.get_function_groups')
def test_auto_compute_features_group_segregation(mock_get_groups, mock_vbt_from_data, mock_hdf5_env):
    storage_dir, file_path = mock_hdf5_env
    
    # Mock TA-Lib Categories
    mock_get_groups.return_value = {
        'Momentum Indicators': ['RSI', 'MACD'],
        'Overlap Studies': ['SMA']
    }
    
    # Mock VBT Pro Output
    mock_vbt_instance = MagicMock()
    mock_vbt_from_data.return_value = mock_vbt_instance
    
    # Création d'un MultiIndex typique de VectorBT Pro
    cols = pd.MultiIndex.from_tuples([
        ('TALIB_RSI', '14', 'real'),
        ('TALIB_SMA', '20', 'real'),
        ('CUSTOM_IND', '10', 'out')
    ])
    mock_features_df = pd.DataFrame(
        np.random.rand(10, 3),
        columns=cols,
        index=pd.to_datetime(np.arange(1000, 11000, 1000), unit='ms')
    )
    mock_vbt_instance.run.return_value = mock_features_df
    
    # Exécution
    auto_compute_features(storage_dir, "BINANCE", "BTCUSDT", "1m")
    
    # Validation de l'arborescence HDF5
    with HDF5Storage(file_path, mode='r') as storage:
        groups = storage.list_groups()
        assert "MOMENTUM_INDICATORS" in groups
        assert "OVERLAP_STUDIES" in groups
        assert "UNCATEGORIZED" in groups
        
    with HDF5Storage(file_path, group_path="/FEATURES/MOMENTUM_INDICATORS", mode='r') as storage:
        momentum_data = storage.read_array(storage.dataset_path)
        assert 'open_time' in momentum_data.dtype.names
        assert 'RSI_14' in momentum_data.dtype.names

    with HDF5Storage(file_path, group_path="/FEATURES/UNCATEGORIZED", mode='r') as storage:
        custom_data = storage.read_array(storage.dataset_path)
        assert 'CUSTOM_IND_10_OUT' in custom_data.dtype.names