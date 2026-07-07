import pytest
import numpy as np
from pathlib import Path
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE

@pytest.fixture
def temp_h5_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "BINANCE" / "BTCUSDT" / "1m" / "test_ohlcv.h5"

def test_hdf5_storage_dynamic_group_path(temp_h5_file: Path) -> None:
    with HDF5Storage(temp_h5_file, group_path="/OHLCV", mode='w') as manager:
        assert manager.dataset_path == "OHLCV"
        
    with HDF5Storage(temp_h5_file, group_path="/FEATURES/MOMENTUM", mode='w') as manager:
        assert manager.dataset_path == "FEATURES/MOMENTUM"

def test_hdf5_storage_list_groups(temp_h5_file: Path) -> None:
    with HDF5Storage(temp_h5_file, mode='w') as manager:
        manager.write_array("OHLCV", np.zeros(5, dtype=OHLCV_DTYPE))
        
        feature_dtype = np.dtype([('open_time', np.int64), ('RSI_14', np.float64)])
        manager.write_array("FEATURES/MOMENTUM", np.zeros(5, dtype=feature_dtype))
        manager.write_array("FEATURES/OVERLAP", np.zeros(5, dtype=feature_dtype))
        
    with HDF5Storage(temp_h5_file, mode='r') as reader:
        groups = reader.list_groups()
        assert "MOMENTUM" in groups
        assert "OVERLAP" in groups
        assert len(groups) == 2

def test_hdf5_manager_creates_directories(temp_h5_file: Path) -> None:
    assert not temp_h5_file.parent.exists()
    with HDF5Storage(temp_h5_file, mode='w', group_path="/OHLCV") as manager:
        manager.write_array(manager.dataset_path, np.zeros(3, dtype=OHLCV_DTYPE))
    assert temp_h5_file.parent.exists()

def test_hdf5_manager_read_write_consistency(temp_h5_file: Path) -> None:
    original_data = np.zeros(2, dtype=OHLCV_DTYPE)
    original_data['open_time'] = [1000, 2000]
    original_data['close'] = [100.5, 101.2]
    
    with HDF5Storage(temp_h5_file, mode='w', group_path="/OHLCV") as manager:
        manager.write_array(manager.dataset_path, original_data)
        
    with HDF5Storage(temp_h5_file, mode='r', group_path="/OHLCV") as manager:
        retrieved_data = manager.read_array(manager.dataset_path)
        
    np.testing.assert_array_equal(original_data['open_time'], retrieved_data['open_time'])
    np.testing.assert_array_equal(original_data['close'], retrieved_data['close'])

def test_hdf5_manager_type_enforcement(temp_h5_file: Path) -> None:
    invalid_data = [1, 2, 3] 
    
    with HDF5Storage(temp_h5_file, mode='w', group_path="/OHLCV") as manager:
        with pytest.raises(TypeError, match="Le format de données doit être un numpy.ndarray"):
            manager.write_array(manager.dataset_path, invalid_data) # type: ignore