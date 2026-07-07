
# tests/test_store_purity.py
import os

def test_store_js_has_no_jsx():
    path = "frontend/src/entities/indicators/store.js"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<div" not in content
    assert "className=" not in content
    assert "</" not in content