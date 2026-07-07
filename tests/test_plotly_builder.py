# tests/test_plotly_builder.py
import os

def test_plotly_builder_anchoring():
    path = "frontend/src/features/ChartEngine/usePlotlyBuilder.js"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "anchor: 'x'" in content
    assert "safeToISOString" in content