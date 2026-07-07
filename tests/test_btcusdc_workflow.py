
# tests/test_btcusdc_workflow.py
import os
import sqlite3
import time
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.gateway import app, app_state
from backend.data.hdf5_storage import HDF5Storage

client = TestClient(app)

class MockBinanceData:
    def __init__(self, df, symbol):
        self.data = {symbol: df}

def generate_mock_df(n_rows=150):
    timestamps = np.arange(1782975419000 - n_rows * 900000, 1782975419000, 900000, dtype=np.int64)
    data = {
        "open": np.random.uniform(100.0, 110.0, n_rows),
        "high": np.random.uniform(110.0, 120.0, n_rows),
        "low": np.random.uniform(90.0, 100.0, n_rows),
        "close": np.random.uniform(100.0, 110.0, n_rows),
        "volume": np.random.uniform(10.0, 100.0, n_rows),
        "quote volume": np.random.uniform(1000.0, 10000.0, n_rows),
        "trade count": np.random.randint(10, 100, n_rows)
    }
    for i in range(n_rows):
        data["high"][i] = max(data["high"][i], data["open"][i], data["close"][i])
        data["low"][i] = min(data["low"][i], data["open"][i], data["close"][i])
        
    df = pd.DataFrame(data)
    df.index = pd.to_datetime(timestamps, unit='ms')
    return df

@pytest.fixture
def setup_btc_env(tmp_path, monkeypatch):
    storage_dir = tmp_path / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
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
        if "runs.db" in database:
            return real_connect(str(db_file), *args, **kwargs)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr("sqlite3.connect", mock_connect)
    return str(storage_dir)

def mom_data_fields(h5_path, group_path):
    with HDF5Storage(h5_path, group_path=group_path, mode='r') as st:
        return st.read_array(st.dataset_path).dtype.names

def hdf5_path_for(setup_resample_env, tf):
    return os.path.join(setup_resample_env, "BINANCE", "BTCUSDC", tf, "ohlcv.h5")

@pytest.mark.asyncio
async def test_complete_btcusdc_workflow(setup_btc_env):
    mock_df = generate_mock_df(150)
    
    with patch("vectorbtpro.BinanceData.fetch", return_value=MockBinanceData(mock_df, "BTCUSDC")):
        payload_fetch = {
            "symbol": "BTCUSDC",
            "start": "15 days ago",
            "end": "now",
            "timeframe": "15m",
            "limit": 1000,
            "delay": 0.5,
            "show_progress": True
        }
        response_fetch = client.post("/api/ingestion/vbt-fetch", json=payload_fetch)
        assert response_fetch.status_code == 200
        task_id = response_fetch.json()["task_id"]
        
        for _ in range(50):
            task_status = client.get(f"/api/tasks/{task_id}").json()
            if task_status["status"] in ["completed", "failed"]:
                assert task_status["status"] == "completed"
                break
            time.sleep(0.1)
            
    h5_15m_path = hdf5_path_for(setup_btc_env, "15m")
    assert os.path.exists(h5_15m_path)
    
    response_vbt_info_15m = client.get("/api/ingestion/vbt-info/BTCUSDC?timeframe=15m")
    assert response_vbt_info_15m.status_code == 200
    indicators_15m = response_vbt_info_15m.json()["indicators"]
    assert "RSI" in indicators_15m
    assert "BBANDS" in indicators_15m

    payload_resample_30m = {
        "symbol": "BTCUSDC",
        "target_timeframe": "30m"
    }
    response_30m = client.post("/api/ingestion/add-timeframe", json=payload_resample_30m)
    assert response_30m.status_code == 200
    assert response_30m.json()["status"] == "success"
    
    h5_30m_path = hdf5_path_for(setup_btc_env, "30m")
    assert os.path.exists(h5_30m_path)
    
    response_vbt_info_30m = client.get("/api/ingestion/vbt-info/BTCUSDC?timeframe=30m")
    assert response_vbt_info_30m.status_code == 200
    assert "RSI" in response_vbt_info_30m.json()["indicators"]

    payload_resample_4h = {
        "symbol": "BTCUSDC",
        "target_timeframe": "4h"
    }
    response_4h = client.post("/api/ingestion/add-timeframe", json=payload_resample_4h)
    assert response_4h.status_code == 200
    
    h5_4h_path = hdf5_path_for(setup_btc_env, "4h")
    assert os.path.exists(h5_4h_path)

    for tf in ["15m", "30m", "4h"]:
        tf_file = hdf5_path_for(setup_btc_env, tf)
        mom_cols = mom_data_fields(tf_file, "/FEATURES/MOMENTUM_INDICATORS")
        overlap_cols = mom_data_fields(tf_file, "/FEATURES/OVERLAP_STUDIES")
        
        assert "RSI" in mom_cols
        assert "BBANDS_UPPERBAND" in overlap_cols

    for tf in ["15m", "30m", "4h"]:
        payload_ohlcv = {
            "exchange": "BINANCE",
            "symbol": "BTCUSDC",
            "timeframe": tf,
            "start_time": 0,
            "end_time": int(time.time() * 1000) + 90000000,
            "features": {
                "OHLCV": ["open", "high", "low", "close"]
            }
        }
        res_ohlcv = client.post("/api/data/ohlcv", json=payload_ohlcv)
        assert res_ohlcv.status_code == 200
        data_ohlcv = res_ohlcv.json()
        assert "open" in data_ohlcv
        assert "close" in data_ohlcv

    for tf in ["15m", "30m", "4h"]:
        tf_file = hdf5_path_for(setup_btc_env, tf)
        mom_cols = mom_data_fields(tf_file, "/FEATURES/MOMENTUM_INDICATORS")
        overlap_cols = mom_data_fields(tf_file, "/FEATURES/OVERLAP_STUDIES")
        
        payload_combo = {
            "exchange": "BINANCE",
            "symbol": "BTCUSDC",
            "timeframe": tf,
            "start_time": 0,
            "end_time": int(time.time() * 1000) + 90000000,
            "features": {
                "OHLCV": ["close"],
                "FEATURES/MOMENTUM_INDICATORS": [col for col in ["RSI"] if col in mom_cols],
                "FEATURES/OVERLAP_STUDIES": [col for col in ["BBANDS_UPPERBAND", "BBANDS_MIDDLEBAND", "BBANDS_LOWERBAND"] if col in overlap_cols]
            }
        }
        res_combo = client.post("/api/data/ohlcv", json=payload_combo)
        assert res_combo.status_code == 200
        data_combo = res_combo.json()
        assert "open_time" in data_combo
        assert "close" in data_combo
        assert "RSI" in data_combo
        assert "BBANDS_UPPERBAND" in data_combo