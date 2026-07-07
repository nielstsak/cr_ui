import pytest
import numpy as np
from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.api.routes_data import router
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture
def mock_hdf5_data(tmp_path, monkeypatch):
    storage_dir = tmp_path / "data"
    symbol_dir = storage_dir / "BINANCE" / "BTCUSDT" / "5m"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    file_path = symbol_dir / "ohlcv.h5"

    ohlcv = np.zeros(5, dtype=OHLCV_DTYPE)
    ohlcv['open_time'] = [1000, 2000, 3000, 4000, 5000]
    ohlcv['close'] = [10.0, 11.0, 12.0, 13.0, 14.0]
    with HDF5Storage(file_path, group_path="/OHLCV", mode='w') as st:
        st.write_array(st.dataset_path, ohlcv)

    feat_dtype = np.dtype([('open_time', np.int64), ('RSI_14', np.float64)])
    feat = np.zeros(5, dtype=feat_dtype)
    feat['open_time'] = [1000, 2000, 3000, 4000, 5000]
    feat['RSI_14'] = [np.nan, 50.0, 60.0, 70.0, np.nan]
    with HDF5Storage(file_path, group_path="/FEATURES/MOMENTUM", mode='a') as st:
        st.write_array(st.dataset_path, feat)

    monkeypatch.setattr("backend.api.routes_data.get_storage_dir", lambda: str(storage_dir))
    return str(storage_dir)

def test_ohlcv_data_join(mock_hdf5_data):
    payload = {
        "exchange": "BINANCE",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "start_time": 1000,
        "end_time": 4000,
        "features": {
            "OHLCV": ["close"],
            "FEATURES/MOMENTUM": ["RSI_14"]
        }
    }

    response = client.post("/api/data/ohlcv", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert "open_time" in data
    assert "close" in data
    assert "RSI_14" in data
    # Correction : searchsorted avec side='left' inclut start_time mais exclut end_time.
    # L'intervalle [1000, 4000[ retourne donc les index 1000, 2000, 3000 (3 éléments).
    assert len(data["open_time"]) == 3 
    assert data["RSI_14"][0] is None
    assert data["RSI_14"][1] == 50.0

def test_ohlcv_data_missing_ohlcv_group(mock_hdf5_data):
    payload = {
        "exchange": "BINANCE",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "start_time": 1000,
        "end_time": 4000,
        "features": {
            "FEATURES/MOMENTUM": ["RSI_14"]
        }
    }
    response = client.post("/api/data/ohlcv", json=payload)
    assert response.status_code == 400
    assert "Le groupe OHLCV est requis" in response.json()["detail"]