
# tests/test_indicators_bulk.py
import pytest
from fastapi.testclient import TestClient
from backend.api.gateway import app

client = TestClient(app)

def test_get_bulk_indicator_metadata_success():
    payload = {"names": ["RSI", "BBANDS", "INVALID_INDICATOR"]}
    response = client.post("/api/indicators/metadata/bulk", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert "RSI" in data
    assert data["RSI"]["name"] == "RSI"
    assert "real" in data["RSI"]["outputs"]
    
    assert "BBANDS" in data
    assert "upperband" in data["BBANDS"]["outputs"]
    
    assert "INVALID_INDICATOR" not in data

def test_get_bulk_indicator_metadata_empty():
    payload = {"names": []}
    response = client.post("/api/indicators/metadata/bulk", json=payload)
    assert response.status_code == 200
    assert response.json() == {}