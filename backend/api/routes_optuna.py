# backend/api/routes_optuna.py
import os
import json
import logging
import asyncio
import traceback
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/optuna", tags=["optuna"])
logger = logging.getLogger("RoutesOptuna")

class OptunaOptimizeRequest(BaseModel):
    symbol: str
    timeframe: str
    target_format: str = "classification"
    target_wick_type: str = "High-Open"
    target_threshold: float = 2.0
    model_type: str = "lightgbm"
    metric_type: str = "sharpe"
    trading_direction: str = "both"
    
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    entry_sig_threshold: float = 0.5

    n_trials: int = 20

    is_length_days_min: int = 15
    is_length_days_max: int = 90
    oos_length_hours_min: int = 12
    oos_length_hours_max: int = 168

    learning_rate_min: float = 0.01
    learning_rate_max: float = 0.3
    max_depth_min: int = 3
    max_depth_max: int = 8
    colsample_bytree_min: float = 0.3
    colsample_bytree_max: float = 1.0

def get_storage_dir() -> str:
    from backend.api.gateway import app_state
    return app_state.state["configurations"].get("storage_dir", "data")

async def _run_optuna_coro(task_id: str, req: OptunaOptimizeRequest):
    from backend.api.gateway import tasks_db
    from backend.core.ml_optuna_engine import MLOptunaEngine
    
    storage_dir = get_storage_dir()
    engine = MLOptunaEngine(storage_dir=storage_dir)
    config = req.dict()
    config["trading_direction"] = "both"
    
    # Callback to update task progress and results after each trial
    def on_trial_complete(trial_num: int, progress_pct: float, trials_list: list):
        # Calculate intermediate Pareto front for real-time frontend visualization
        # Sort complete trials to find non-dominated ones
        completed = [t for t in trials_list if t["state"] == "COMPLETE"]
        pareto_indices = []
        for i, t1 in enumerate(completed):
            dominated = False
            for j, t2 in enumerate(completed):
                if i == j:
                    continue
                # t2 dominates t1 if:
                # 1. t2.metric >= t1.metric AND t2.mdd <= t1.mdd
                # AND at least one inequality is strict
                v1_0, v1_1 = t1["values"][0], t1["values"][1]
                v2_0, v2_1 = t2["values"][0], t2["values"][1]
                if v2_0 >= v1_0 and v2_1 <= v1_1:
                    if v2_0 > v1_0 or v2_1 < v1_1:
                        dominated = True
                        break
            if not dominated:
                pareto_indices.append(t1["trial_number"])

        tasks_db[task_id]["progress"] = progress_pct
        tasks_db[task_id]["result"] = {
            "current_trial": trial_num,
            "trials": [
                {
                    "trial_number": t["trial_number"],
                    "params": t["params"],
                    "values": t["values"],
                    "metrics": t["metrics"]
                }
                for t in trials_list
            ],
            "pareto_front": pareto_indices
        }
        
    loop = asyncio.get_running_loop()
    
    # Run CPU-bound training in executor
    try:
        results = await loop.run_in_executor(
            None,
            engine.run_optuna_study,
            task_id, # Use task_id as study_id
            config,
            on_trial_complete
        )
        return results
    except Exception as e:
        logger.error(f"Error in WFO Optuna task {task_id}: {e}\n{traceback.format_exc()}")
        raise e

@router.post("/optimize")
async def run_optuna_optimization(req: OptunaOptimizeRequest):
    from backend.api.gateway import run_async_background_task
    # Launch backtest in background
    task_id = run_async_background_task(_run_optuna_coro, req=req)
    return {"task_id": task_id, "status": "running"}

@router.get("/studies")
async def list_optuna_studies():
    storage_dir = get_storage_dir()
    studies_dir = os.path.join(storage_dir, "optuna_studies")
    if not os.path.exists(studies_dir):
        return []
        
    studies = []
    for file in os.listdir(studies_dir):
        if file.endswith(".json"):
            file_path = os.path.join(studies_dir, file)
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # Skip files that are not valid Optuna studies
                # (e.g. TAOUSDC_best.json or other metadata files)
                if "trials" not in data and "pareto_front" not in data:
                    continue
                
                # Check status and read config
                studies.append({
                    "study_id": data.get("study_id"),
                    "created_at": data.get("created_at"),
                    "config": data.get("config"),
                    "trials_count": len(data.get("trials", [])),
                    "pareto_count": len(data.get("pareto_front", []))
                })
            except Exception as e:
                logger.error(f"Error reading study file {file}: {e}")
                
    # Sort by created_at descending, handling None values gracefully
    studies.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return studies

@router.get("/studies/{study_id}/details")
async def get_study_details(study_id: str):
    storage_dir = get_storage_dir()
    file_path = os.path.join(storage_dir, "optuna_studies", f"{study_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Étude introuvable.")
        
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error(f"Error reading study details for {study_id}: {e}")
        raise HTTPException(status_code=500, detail="Impossible de lire les détails de l'étude.")

@router.delete("/studies/{study_id}")
async def delete_study(study_id: str):
    storage_dir = get_storage_dir()
    file_path = os.path.join(storage_dir, "optuna_studies", f"{study_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Étude introuvable.")
        
    try:
        os.remove(file_path)
        return {"status": "success", "message": "Étude supprimée."}
    except Exception as e:
        logger.error(f"Error deleting study file for {study_id}: {e}")
        raise HTTPException(status_code=500, detail="Impossible de supprimer l'étude.")

@router.get("/features/symbols")
async def list_feature_symbols():
    storage_dir = get_storage_dir()
    features_dir = os.path.join(storage_dir, "optuna_features")
    if not os.path.exists(features_dir):
        return []
    symbols = []
    for item in os.listdir(features_dir):
        item_path = os.path.join(features_dir, item)
        if os.path.isdir(item_path):
            symbols.append(item)
    return sorted(symbols)

@router.delete("/features/symbols/{symbol}")
async def delete_feature_symbol(symbol: str):
    storage_dir = get_storage_dir()
    symbol_dir = os.path.join(storage_dir, "optuna_features", symbol)
    if not os.path.exists(symbol_dir):
        raise HTTPException(status_code=404, detail="Dossier de features introuvable.")
    try:
        import shutil
        shutil.rmtree(symbol_dir)
        return {"status": "success", "message": f"Dossier de features pour {symbol} supprimé."}
    except Exception as e:
        logger.error(f"Error deleting features folder for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Impossible de supprimer le dossier de features.")

class OptunaDefaultsModel(BaseModel):
    target_format: str
    target_threshold: float
    entry_sig_threshold: float
    model_type: str
    metric_type: str
    is_length_days_min: int
    is_length_days_max: int
    oos_length_hours_min: int
    oos_length_hours_max: int
    learning_rate_min: float
    learning_rate_max: float
    max_depth_min: int
    max_depth_max: int
    colsample_bytree_min: float
    colsample_bytree_max: float

@router.get("/defaults")
async def get_optuna_defaults():
    from backend.api.gateway import app_state
    defaults = app_state.state["configurations"].get("optuna_defaults", {})
    return defaults

@router.post("/defaults")
async def save_optuna_defaults(req: OptunaDefaultsModel):
    from backend.api.gateway import app_state
    app_state.state["configurations"]["optuna_defaults"] = req.dict()
    app_state.save()
    return {"status": "success", "message": "Paramètres par défaut enregistrés."}

@router.get("/agentic-loop")
async def get_agentic_loop_status():
    storage_dir = get_storage_dir()
    status_file = os.path.join(storage_dir, "optuna_studies", "agentic_loop_status.json")
    if not os.path.exists(status_file):
        return {"status": "idle", "history": []}
    try:
        with open(status_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error(f"Error reading agentic loop status: {e}")
        return {"status": "idle", "history": []}

