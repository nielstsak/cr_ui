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
def setup_complex_hdf5(tmp_path, monkeypatch):
    storage_dir = tmp_path / "data"
    symbol_dir = storage_dir / "BINANCE" / "ETHUSDT" / "1h"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    file_path = symbol_dir / "ohlcv.h5"

    ohlcv = np.zeros(3, dtype=OHLCV_DTYPE)
    ohlcv['open_time'] = [1000000, 2000000, 3000000]
    ohlcv['open'] = [99.0, 101.0, 106.0]
    ohlcv['high'] = [101.0, 106.0, 111.0]
    ohlcv['low'] = [98.0, 100.0, 105.0]
    ohlcv['close'] = [100.0, 105.0, 110.0]
    ohlcv['volume'] = [10.0, 15.0, 20.0]
    with HDF5Storage(file_path, group_path="/OHLCV", mode='w') as st:
        st.write_array(st.dataset_path, ohlcv)

    mom_dtype = np.dtype([('open_time', np.int64), ('RSI_14', np.float64)])
    mom_data = np.zeros(3, dtype=mom_dtype)
    mom_data['open_time'] = [1000000, 2000000, 3000000]
    mom_data['RSI_14'] = [30.0, np.inf, -np.inf]
    with HDF5Storage(file_path, group_path="/FEATURES/MOMENTUM_INDICATORS", mode='a') as st:
        st.write_array(st.dataset_path, mom_data)

    ov_dtype = np.dtype([('open_time', np.int64), ('SMA_20', np.float64)])
    ov_data = np.zeros(3, dtype=ov_dtype)
    ov_data['open_time'] = [1000000, 2000000, 3000000]
    ov_data['SMA_20'] = [98.5, 100.2, 104.5]
    with HDF5Storage(file_path, group_path="/FEATURES/OVERLAP_STUDIES", mode='a') as st:
        st.write_array(st.dataset_path, ov_data)

    monkeypatch.setattr("backend.api.routes_data.get_storage_dir", lambda: str(storage_dir))
    return str(storage_dir)

def test_complex_multi_group_join(setup_complex_hdf5):
    payload = {
        "exchange": "BINANCE",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "start_time": 1000000,
        "end_time": 4000000,
        "features": {
            "OHLCV": ["open", "close"],
            "FEATURES/MOMENTUM_INDICATORS": ["RSI_14"],
            "FEATURES/OVERLAP_STUDIES": ["SMA_20"]
        }
    }
    response = client.post("/api/data/ohlcv", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "open_time" in data
    assert "open" in data
    assert "close" in data
    assert "RSI_14" in data
    assert "SMA_20" in data

    assert data["RSI_14"][0] == 30.0
    assert data["RSI_14"][1] is None
    assert data["RSI_14"][2] is None
    assert data["SMA_20"] == [98.5, 100.2, 104.5]

def test_missing_symbol_file_returns_400(setup_complex_hdf5):
    payload = {
        "exchange": "BINANCE",
        "symbol": "NOTFOUND",
        "timeframe": "1h",
        "start_time": 1000000,
        "end_time": 4000000,
        "features": {
            "OHLCV": ["close"]
        }
    }
    response = client.post("/api/data/ohlcv", json=payload)
    assert response.status_code == 400
    assert "introuvable" in response.json()["detail"]