# FICHIER : backend/tests/test_hdf5_storage.py
import pytest
import numpy as np
from pathlib import Path
from backend.data.hdf5_storage import HDF5Storage

@pytest.fixture
def temp_h5_file(tmp_path: Path) -> Path:
    """Fixture fournissant un chemin temporaire pour les tests HDF5."""
    return tmp_path / "data" / "BINANCE" / "BTCUSDT" / "1m" / "test_ohlcv.h5"

def test_hdf5_manager_creates_directories(temp_h5_file: Path) -> None:
    """Vérifie que le gestionnaire crée l'arborescence de dossiers manquante."""
    assert not temp_h5_file.parent.exists()
    
    with HDF5Storage(temp_h5_file, mode='w') as manager:
        manager.write_array("test_group/mock_data", np.array([1, 2, 3], dtype=np.float64))
        
    assert temp_h5_file.parent.exists()
    assert temp_h5_file.exists()

def test_hdf5_manager_read_write_consistency(temp_h5_file: Path) -> None:
    """Vérifie l'intégrité des données numériques lors d'un cycle écriture/lecture."""
    original_data = np.array([[100.5, 101.2], [101.2, 99.8]], dtype=np.float32)
    dataset_path = "market_data/ohlcv"
    
    with HDF5Storage(temp_h5_file, mode='w') as manager:
        manager.write_array(dataset_path, original_data)
        
    with HDF5Storage(temp_h5_file, mode='r') as manager:
        retrieved_data = manager.read_array(dataset_path)
        
    np.testing.assert_array_equal(original_data, retrieved_data)
    assert retrieved_data.dtype == np.float32

def test_hdf5_manager_type_enforcement(temp_h5_file: Path) -> None:
    """Vérifie que seules les structures NumPy sont acceptées pour Numba/VectorBT."""
    invalid_data = [1, 2, 3]  # Liste native Python (non optimisée)
    
    with HDF5Storage(temp_h5_file, mode='w') as manager:
        with pytest.raises(TypeError, match="Le format de données doit être un numpy.ndarray"):
            manager.write_array("market_data/invalid", invalid_data) # type: ignore

def test_hdf5_manager_swmr_mode(temp_h5_file: Path) -> None:
    """Vérifie l'activation du mode Single-Writer/Multiple-Reader (SWMR)."""
    data = np.arange(10, dtype=np.int32)
    
    with HDF5Storage(temp_h5_file, mode='w') as manager:
        # SWMR nécessite que les datasets soient 'chunked'
        manager.write_array("swmr_data", data, maxshape=(None,), chunks=True)
        manager.enable_swmr()
        assert manager.file is not None
        assert manager.file.swmr_mode is True