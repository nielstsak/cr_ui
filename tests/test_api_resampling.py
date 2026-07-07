
import pytest
import sqlite3
import os
import numpy as np
from fastapi.testclient import TestClient
from backend.api.gateway import app, app_state
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE

client = TestClient(app)

@pytest.fixture
def setup_resample_env(tmp_path, monkeypatch):
    storage_dir = tmp_path / "data"
    symbol_dir = storage_dir / "BINANCE" / "LTCUSDT" / "5m"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    file_path = symbol_dir / "ohlcv.h5"

    ohlcv = np.zeros(10, dtype=OHLCV_DTYPE)
    ohlcv['open_time'] = [1000000 + i * 300000 for i in range(10)]
    ohlcv['open'] = [10.0 + i for i in range(10)]
    ohlcv['high'] = [11.0 + i for i in range(10)]
    ohlcv['low'] = [9.0 + i for i in range(10)]
    ohlcv['close'] = [10.5 + i for i in range(10)]
    ohlcv['volume'] = [100.0 for _ in range(10)]

    with HDF5Storage(file_path, group_path="/OHLCV", mode='w') as st:
        st.write_array(st.dataset_path, ohlcv)

    db_file = tmp_path / "runs.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            timeframe TEXT,
            sample_size INTEGER,
            period_start TEXT,
            period_end TEXT,
            kick_threshold REAL,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(app_state, "state", {
        "active_pairs": [],
        "configurations": {
            "initial_balance": 10000.0,
            "fee_rate": 0.0004,
            "slippage_rate": 0.0005,
            "mmr": 0.05,
            "leverage": 1.0,
            "storage_dir": str(storage_dir)
        }
    })

    real_connect = sqlite3.connect
    def mock_connect(database, *args, **kwargs):
        return real_connect(str(db_file), *args, **kwargs)

    monkeypatch.setattr("sqlite3.connect", mock_connect)
    return str(storage_dir)

def test_add_timeframe_endpoint(setup_resample_env):
    payload = {
        "symbol": "LTCUSDT",
        "target_timeframe": "15m"
    }
    response = client.post("/api/ingestion/add-timeframe", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["timeframe_added"] == "15m"

    target_path = os.path.join(setup_resample_env, "BINANCE", "LTCUSDT", "15m", "ohlcv.h5")
    assert os.path.exists(target_path)

    with HDF5Storage(target_path, group_path="/OHLCV", mode='r') as st:
        resampled = st.read_array(st.dataset_path)
        assert len(resampled) > 0