# backend/api/routes_feature_engineering.py
import os
import sqlite3
import asyncio
import logging
import numpy as np
import pandas as pd
import pydantic
from typing import List, Dict
from fastapi import APIRouter, HTTPException
from talib import get_function_groups, abstract

from backend.data.hdf5_storage import HDF5Storage
from backend.core.indicators import DynamicIndicatorFactory, get_talib_metadata

logger = logging.getLogger("FeatureEngineeringAPI")
router = APIRouter(prefix="/api/features", tags=["features"])

class FeatureDeepenRequest(pydantic.BaseModel):
    symbol: str
    indicator_types: List[str]

def timeframe_to_minutes(tf: str) -> int:
    """
    Converts a timeframe string (e.g. '5m', '2h', '1d') into integer minutes.
    """
    tf = tf.lower().strip()
    if tf.endswith('m'):
        return int(tf[:-1])
    elif tf.endswith('h'):
        return int(tf[:-1]) * 60
    elif tf.endswith('d'):
        return int(tf[:-1]) * 1440
    elif tf.endswith('w'):
        return int(tf[:-1]) * 10080
    else:
        raise ValueError(f"Timeframe format inconnu : {tf}")

def get_column_name(indicator_name: str, timeframe: str, output_name: str, params: dict) -> str:
    """
    Builds a clean, readable and optimized column name.
    If the output is 'real' and there's only one output, we omit it.
    """
    # Shorten parameter names
    param_parts = []
    for k, v in sorted(params.items()):
        short_k = k
        if k == 'timeperiod':
            short_k = 'w'
        elif k == 'fastperiod':
            short_k = 'fast'
        elif k == 'slowperiod':
            short_k = 'slow'
        elif k == 'signalperiod':
            short_k = 'sig'
        param_parts.append(f"{short_k}{v}")
    
    param_suffix = "_".join(param_parts)
    
    # Try to see if it has only 'real' output
    try:
        meta = get_talib_metadata(indicator_name.upper())
        outputs = meta.get("outputs", [])
    except Exception:
        outputs = []
        
    if len(outputs) <= 1 and output_name.lower() == 'real':
        return f"{indicator_name.upper()}_{timeframe.lower()}_{param_suffix}"
    else:
        return f"{indicator_name.upper()}_{timeframe.lower()}_{output_name.lower()}_{param_suffix}"

async def _deepen_features_coro(task_id: str, req: FeatureDeepenRequest):
    from backend.api.gateway import app_state, tasks_db
    symbol = req.symbol.upper().replace("/", "")
    storage_dir = app_state.state["configurations"].get("storage_dir", "data")
    
    # 1. Detect existing timeframes
    base_dir = os.path.join(storage_dir, "BINANCE", symbol)
    if not os.path.exists(base_dir):
        raise ValueError(f"Aucune donnée ingérée trouvée pour le symbole {symbol}.")
        
    tf_dirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    if not tf_dirs:
        raise ValueError(f"Aucun timeframe trouvé pour le symbole {symbol}.")
        
    tasks_db[task_id]["progress"] = 10.0
    
    # 2. Sort timeframes by duration
    tf_durations = []
    for tf in tf_dirs:
        try:
            minutes = timeframe_to_minutes(tf)
            tf_durations.append((tf, minutes))
        except ValueError:
            logger.warning(f"Ignoré: Timeframe invalide {tf}")
            
    # Sort ascending
    tf_durations.sort(key=lambda x: x[1])
    sorted_tfs = [x[0] for x in tf_durations]
    
    # 3. Calculate ratios between successive timeframes
    ratios = {}
    for i in range(len(tf_durations) - 1):
        tf_current, dur_current = tf_durations[i]
        tf_next, dur_next = tf_durations[i+1]
        ratio = dur_next / dur_current
        ratios[tf_current] = int(round(ratio))
        
    logger.info(f"Timeframes triés pour {symbol}: {sorted_tfs}. Ratios calculés: {ratios}")
    tasks_db[task_id]["progress"] = 20.0
    
    # 4. Resolve selected indicator groups
    talib_groups = get_function_groups()
    selected_funcs = []
    for group_name in req.indicator_types:
        if group_name in talib_groups:
            selected_funcs.extend(talib_groups[group_name])
            
    # Remove duplicates
    selected_funcs = list(dict.fromkeys(selected_funcs))
    if not selected_funcs:
        raise ValueError("Aucun indicateur valide trouvé pour les types sélectionnés.")
        
    logger.info(f"Indicateurs sélectionnés ({len(selected_funcs)}) : {selected_funcs}")
    tasks_db[task_id]["progress"] = 30.0
    
    # 5. Process each timeframe
    n_tfs = len(sorted_tfs)
    for tf_idx, tf in enumerate(sorted_tfs):
        logger.info(f"Traitement du timeframe {tf} ({tf_idx + 1}/{n_tfs})")
        tf_path = os.path.join(base_dir, tf, "ohlcv.h5")
        if not os.path.exists(tf_path):
            logger.warning(f"Fichier de base introuvable pour {symbol} {tf} : {tf_path}")
            continue
            
        # Read base OHLCV
        with HDF5Storage(tf_path, mode='r', group_path="/OHLCV") as storage:
            ohlcv_arr = storage.read_array(storage.dataset_path)
            
        if len(ohlcv_arr) == 0:
            logger.warning(f"Données OHLCV vides pour {symbol} {tf}")
            continue
            
        open_time = ohlcv_arr['open_time']
        n_candles = len(open_time)
        
        inputs = {
            'open': ohlcv_arr['open'],
            'high': ohlcv_arr['high'],
            'low': ohlcv_arr['low'],
            'close': ohlcv_arr['close'],
            'volume': ohlcv_arr['volume']
        }
        
        # Dictionary to store columns: name -> np.ndarray
        columns_data = {}
        
        # Loop over selected indicators
        for f_idx, func_name in enumerate(selected_funcs):
            try:
                meta = get_talib_metadata(func_name.upper())
                params_schema = meta.get("parameters", {})
            except Exception as e:
                logger.warning(f"Impossible d'inspecter {func_name} : {e}")
                continue
                
            # Check if indicator has integer period/window parameters
            period_params = []
            for p_name, p_default in params_schema.items():
                if "period" in p_name.lower() and isinstance(p_default, int):
                    period_params.append(p_name)
                    
            if not period_params:
                # Omit indicators that are not compatible (do not have period/window parameter)
                continue
                
            # Default values
            default_params = {p: params_schema[p] for p in period_params}
            
            # Determine values of k (scaling multiplier)
            # If tf has a next timeframe, scale from 1 up to ratio
            ratio = ratios.get(tf, 1)
            k_values = list(range(1, ratio + 1))
            
            for k in k_values:
                # Build scaled parameters
                override_params = {}
                # Keep other non-period parameters as default
                for p_name, p_default in params_schema.items():
                    if p_name in period_params:
                        override_params[p_name] = p_default * k
                    else:
                        override_params[p_name] = p_default
                        
                # Compute indicator
                try:
                    res = DynamicIndicatorFactory.run_indicator(
                        func_name.upper(),
                        inputs,
                        override_params,
                        downcast_float32=True
                    )
                    
                    # For each output, save the column
                    for out_name, out_arr in res["outputs"].items():
                        # out_arr has shape (n_candles, n_combinations)
                        # since we passed scalar overrides, n_combinations is 1
                        series = out_arr[:, 0]
                        
                        col_name = get_column_name(func_name, tf, out_name, override_params)
                        columns_data[col_name] = series
                except Exception as e:
                    logger.warning(f"Erreur de calcul de {func_name} (k={k}) sur {tf} : {e}")
                    
        # 6. Save computed columns for this timeframe
        if columns_data:
            # Build structured array
            dtype_fields = [('open_time', np.int64)]
            for col in sorted(columns_data.keys()):
                dtype_fields.append((col, np.float32))
                
            structured_dtype = np.dtype(dtype_fields)
            records = np.empty(n_candles, dtype=structured_dtype)
            records['open_time'] = open_time
            
            for col, val_arr in columns_data.items():
                records[col] = val_arr
                
            # Target file path
            dest_dir = os.path.join(storage_dir, "optuna_features", symbol)
            os.makedirs(dest_dir, exist_ok=True)
            dest_file = os.path.join(dest_dir, f"{tf}.h5")
            
            if os.path.exists(dest_file):
                os.remove(dest_file)
                
            with HDF5Storage(dest_file, mode='w', group_path="/features") as storage:
                storage.write_array(storage.dataset_path, records)
                
            logger.info(f"Fichier de features approfondies écrit pour {tf} : {dest_file} ({len(columns_data)} colonnes)")
            
        # Update progress based on timeframes processed
        tasks_db[task_id]["progress"] = 30.0 + (tf_idx + 1) / n_tfs * 70.0

    logger.info(f"Tâche de feature engineering terminée avec succès pour {symbol} !")
    return {"symbol": symbol, "timeframes_processed": sorted_tfs}

@router.post("/deepen")
async def deepen_features(req: FeatureDeepenRequest):
    from backend.api.gateway import app_state, run_async_background_task
    # Check if there is already an active ingestion or task (optional)
    task_id = run_async_background_task(_deepen_features_coro, req=req)
    return {"task_id": task_id, "status": "running"}

@router.get("/deepened-columns/{symbol}")
async def get_deepened_columns(symbol: str):
    from backend.api.gateway import app_state
    symbol = symbol.upper().replace("/", "")
    storage_dir = app_state.state["configurations"].get("storage_dir", "data")
    deepened_dir = os.path.join(storage_dir, "optuna_features", symbol)
    
    if not os.path.exists(deepened_dir):
        return {}
        
    results = {}
    try:
        for file in os.listdir(deepened_dir):
            if file.endswith(".h5"):
                tf = file[:-3]
                file_path = os.path.join(deepened_dir, file)
                
                with HDF5Storage(file_path, mode='r', group_path="/features") as storage:
                    if storage.dataset_path in storage.file:
                        fields = storage.file[storage.dataset_path].dtype.names
                        results[tf] = [f for f in fields if f != 'open_time']
    except Exception as e:
        logger.error(f"Erreur lors de la lecture des colonnes approfondies de {symbol} : {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    return results
