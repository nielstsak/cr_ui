
# backend/api/routes_indicators.py
import os
import asyncio
import pydantic
from fastapi import APIRouter, HTTPException
from talib import abstract, get_function_groups
from backend.core.indicator_engine import auto_compute_features

router = APIRouter(prefix="/api", tags=["indicators"])

class IndicatorApplyRequest(pydantic.BaseModel):
    symbol: str

class BulkMetadataRequest(pydantic.BaseModel):
    names: list[str]

@router.get("/indicators/groups")
async def get_indicator_groups():
    return get_function_groups()

@router.post("/indicators/apply")
async def apply_indicators_to_hdf5(req: IndicatorApplyRequest):
    from backend.api.gateway import app_state
    try:
        loop = asyncio.get_running_loop()
        storage_dir = app_state.state["configurations"]["storage_dir"]
        
        def run_mass_compute():
            symbol_dir = os.path.join(storage_dir, "BINANCE", req.symbol.upper())
            if os.path.exists(symbol_dir):
                tfs = [d for d in os.listdir(symbol_dir) if os.path.isdir(os.path.join(symbol_dir, d))]
                for tf in tfs:
                    auto_compute_features(storage_dir, "BINANCE", req.symbol.upper(), tf)
                    
        await loop.run_in_executor(None, run_mass_compute)
        return {"status": "success", "message": "Feature Engineering VectorBT Pro réappliqué."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/indicator/metadata/{func_name}")
async def get_indicator_metadata(func_name: str):
    try:
        ind_func = abstract.Function(func_name.upper())
        return {
            "name": ind_func.info.get("name", func_name.upper()),
            "outputs": list(ind_func.info.get("output_names", []))
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/indicators/metadata/bulk")
async def get_bulk_indicator_metadata(req: BulkMetadataRequest):
    results = {}
    for name in req.names:
        try:
            ind_func = abstract.Function(name.upper())
            results[name] = {
                "name": ind_func.info.get("name", name.upper()),
                "outputs": list(ind_func.info.get("output_names", []))
            }
        except Exception:
            pass
    return results