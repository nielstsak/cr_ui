
# backend/api/routes_ingestion.py
import os
import time
import shutil
import sqlite3
import asyncio
import numpy as np
import pandas as pd
import pydantic
import vectorbtpro as vbt
from typing import Optional
from fastapi import APIRouter, HTTPException
from talib import abstract

from backend.core.resampler import resample_ohlcv
from backend.core.indicator_engine import auto_compute_features
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])

class VbtFetchRequest(pydantic.BaseModel):
    symbol: str
    client: Optional[str] = None
    start: Optional[str] = "1 year ago"
    end: Optional[str] = "now"
    timeframe: Optional[str] = "5m"
    limit: Optional[int] = 1000
    delay: Optional[float] = 0.5
    show_progress: Optional[bool] = True

class AddTimeframeRequest(pydantic.BaseModel):
    symbol: str
    target_timeframe: str

async def _vbt_fetch_coro(task_id: str, req: VbtFetchRequest):
    from backend.api.gateway import app_state, tasks_db
    symbol = req.symbol.upper().replace("/", "")
    tf = req.timeframe.lower() if req.timeframe else "5m"
    
    pair_record = {"symbol": symbol, "timeframe": tf, "status": "ingesting", "task_id": task_id}
    app_state.state["active_pairs"].append(pair_record)
    app_state.save()
    
    try:
        loop = asyncio.get_running_loop()
        def do_fetch():
            fetch_kwargs = {"symbols": symbol, "timeframe": tf}
            if req.client: fetch_kwargs["client"] = req.client
            if req.start: fetch_kwargs["start"] = req.start
            if req.end: fetch_kwargs["end"] = req.end
            if req.limit: fetch_kwargs["limit"] = req.limit
            if req.delay is not None: fetch_kwargs["delay"] = req.delay
            if req.show_progress is not None: fetch_kwargs["show_progress"] = req.show_progress
            return vbt.BinanceData.fetch(**fetch_kwargs)

        tasks_db[task_id]["progress"] = 30.0
        vbt_data = await loop.run_in_executor(None, do_fetch)
        tasks_db[task_id]["progress"] = 60.0
        
        if symbol in vbt_data.data: df = vbt_data.data[symbol]
        else: df = list(vbt_data.data.values())[0]
            
        n = len(df)
        if n == 0: raise ValueError(f"VectorBT a retourné un DataFrame vide pour {symbol}.")
            
        chunk = np.empty(n, dtype=OHLCV_DTYPE)
        chunk['open_time'] = df.index.astype('int64') // 10**6  
        
        def get_col(candidates, default=0.0):
            for c in candidates:
                for col in df.columns:
                    if c == col.lower(): return df[col].values
            return np.full(n, default)

        chunk['open'] = get_col(['open'])
        chunk['high'] = get_col(['high'])
        chunk['low'] = get_col(['low'])
        chunk['close'] = get_col(['close'])
        chunk['volume'] = get_col(['volume', 'base volume'])
        chunk['quote_vol'] = get_col(['quote volume', 'quote_volume'])
        chunk['trades'] = get_col(['trade count', 'number of trades', 'trades'])
        
        storage_dir = app_state.state["configurations"]["storage_dir"]
        tf_dir = os.path.join(storage_dir, "BINANCE", symbol, tf)
        os.makedirs(tf_dir, exist_ok=True)
        tf_file_path = os.path.join(tf_dir, "ohlcv.h5")
        
        if os.path.exists(tf_file_path): os.remove(tf_file_path)
        with HDF5Storage(tf_file_path, "BINANCE", symbol, tf, mode='w', group_path="/OHLCV") as tf_storage:
            tf_storage.write_array(tf_storage.dataset_path, chunk, maxshape=(None,), chunks=True)
        
        conn = sqlite3.connect("data/runs.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM runs WHERE symbol = ? AND timeframe = ?", (symbol, tf))
        start_str = pd.to_datetime(chunk[0]['open_time'], unit='ms').strftime('%Y-%m-%d')
        end_str = pd.to_datetime(chunk[-1]['open_time'], unit='ms').strftime('%Y-%m-%d')
        cursor.execute("""
            INSERT INTO runs (symbol, timeframe, sample_size, period_start, period_end, kick_threshold, timestamp)
            VALUES (?, ?, ?, ?, ?, 2.0, datetime('now'))
        """, (symbol, tf, len(chunk), start_str, end_str))
        conn.commit()
        conn.close()

        tasks_db[task_id]["progress"] = 80.0
        
        await loop.run_in_executor(None, auto_compute_features, storage_dir, "BINANCE", symbol, tf)

        tasks_db[task_id]["progress"] = 100.0
        return {"symbol": symbol, "timeframe": tf, "candles": len(chunk)}
    except Exception as e:
        raise e
    finally:
        app_state.state["active_pairs"] = [p for p in app_state.state["active_pairs"] if p["symbol"] != symbol]
        app_state.save()

@router.post("/vbt-fetch")
async def start_vbt_fetch(req: VbtFetchRequest):
    from backend.api.gateway import app_state, run_async_background_task
    for p in app_state.state["active_pairs"]:
        if p["symbol"] == req.symbol.upper() and p["status"] == "ingesting":
            raise HTTPException(status_code=400, detail="Une ingestion est déjà en cours.")
    task_id = run_async_background_task(_vbt_fetch_coro, req=req)
    return {"task_id": task_id, "status": "running"}

@router.get("/vbt-info/{symbol}")
async def get_vbt_info(symbol: str, timeframe: Optional[str] = None):
    from backend.api.gateway import app_state
    symbol = symbol.upper().replace("/", "")
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol)
    if not os.path.exists(base_dir): raise HTTPException(status_code=404, detail="Introuvable.")
    try:
        tf_dirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        if not tf_dirs:
            raise HTTPException(status_code=404, detail="Aucun timeframe trouvé localement.")
            
        target_tf = timeframe.lower() if timeframe else tf_dirs[0]
        if target_tf not in tf_dirs:
            target_tf = tf_dirs[0]
            
        h5_file = os.path.join(base_dir, target_tf, "ohlcv.h5")
        
        with HDF5Storage(h5_file, "BINANCE", symbol, target_tf, mode='r', group_path="/OHLCV") as storage:
            arr = storage.read_array(storage.dataset_path)
            
        indicators_found = set()
        with HDF5Storage(h5_file, "BINANCE", symbol, target_tf, mode='r') as storage:
            for group in storage.list_groups():
                with HDF5Storage(h5_file, "BINANCE", symbol, target_tf, mode='r', group_path=f"/FEATURES/{group}") as g_st:
                    group_arr = g_st.read_array(g_st.dataset_path)
                    for col in group_arr.dtype.names:
                        if col != 'open_time':
                            parts = col.split('_')
                            found_fn = None
                            for i in range(len(parts), 0, -1):
                                candidate = "_".join(parts[:i]).upper()
                                try:
                                    abstract.Function(candidate)
                                    found_fn = candidate
                                    break
                                except Exception:
                                    pass
                            base_name = found_fn if found_fn else parts[0].upper()
                            indicators_found.add(base_name)
        
        df = pd.DataFrame(arr)        
        df.index = pd.to_datetime(df['open_time'], unit='ms')
        df = df.drop(columns=['open_time'])
        vbt_data = vbt.Data.from_data({symbol: df})
        
        import sys
        import io
        old_stdout = sys.stdout
        new_stdout = io.StringIO()
        sys.stdout = new_stdout
        try: vbt_data.data[symbol].info()
        except Exception: pass
        sys.stdout = old_stdout
        info_str = new_stdout.getvalue()
        
        stats_series = vbt_data.stats()
        stats_dict = {str(k): str(v) for k, v in stats_series.items()}
        
        return {
            "info": info_str, 
            "stats": stats_dict, 
            "indicators": list(indicators_found)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_ingestion_status():
    from backend.api.gateway import app_state
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE")
    local_symbols = []
    if os.path.exists(base_dir):
        for name in os.listdir(base_dir):
            sym_dir = os.path.join(base_dir, name)
            if os.path.isdir(sym_dir):
                timeframes = os.listdir(sym_dir)
                local_symbols.append({"symbol": name, "status": "idle", "timeframe": ", ".join(timeframes)})
    for active in app_state.state["active_pairs"]:
        found = False
        for sym in local_symbols:
            if sym["symbol"] == active["symbol"]:
                sym["status"] = "ingesting"
                found = True
        if not found:
            local_symbols.append({"symbol": active["symbol"], "status": "ingesting", "timeframe": "MTF"})
    return {"active_pairs": local_symbols}

@router.get("/stats/{symbol}")
async def get_symbol_descriptive_stats(symbol: str):
    from backend.api.gateway import app_state
    symbol = symbol.upper().replace("/", "")
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol)
    if not os.path.exists(base_dir): return {} 
    stats = {}
    for tf_dir in os.listdir(base_dir):
        tf_path = os.path.join(base_dir, tf_dir)
        if not os.path.isdir(tf_path): continue
        h5_file = os.path.join(tf_path, "ohlcv.h5")
        if not os.path.exists(h5_file): continue
        try:
            with HDF5Storage(h5_file, "BINANCE", symbol, tf_dir, mode='r', group_path="/OHLCV") as storage:
                data = storage.read_array(storage.dataset_path)
            if len(data) == 0: continue
            
            closes = data['close']
            opens = data['open']
            highs = data['high']
            lows = data['low']
            volumes = data['volume']
            
            stats[tf_dir] = {
                "klines": len(data),
                "start_date": pd.to_datetime(data[0]['open_time'], unit='ms').strftime('%Y-%m-%d %H:%M'),
                "end_date": pd.to_datetime(data[-1]['open_time'], unit='ms').strftime('%Y-%m-%d %H:%M'),
                "green_count": int(np.sum(closes > opens)),
                "red_count": int(np.sum(closes < opens)),
                "min_price": round(float(np.min(lows)), 4),
                "max_price": round(float(np.max(highs)), 4),
                "hold_ratio_pct": round(float((closes[-1] - opens[0]) / opens[0] * 100), 2),
                "avg_volume": round(float(np.mean(volumes)), 2),
                "avg_upper_wick_pct": round(float(np.mean((highs - np.maximum(opens, closes)) / closes)) * 100, 3),
                "avg_lower_wick_pct": round(float(np.mean((np.minimum(opens, closes) - lows) / closes)) * 100, 3)
            }
        except Exception: continue
    return stats

@router.delete("/delete/{symbol}")
async def purge_symbol_data(symbol: str):
    from backend.api.gateway import app_state, sync_database_with_disk
    symbol = symbol.upper().replace("/", "")
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol)
    if os.path.exists(base_dir): shutil.rmtree(base_dir)
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM runs WHERE symbol = ?", (symbol,))
    conn.commit()
    conn.close()
    sync_database_with_disk()
    return {"status": "success", "message": f"Purge complète effectuée pour {symbol}."}

@router.post("/add-timeframe")
async def add_timeframe_via_resampling(req: AddTimeframeRequest):
    from backend.api.gateway import app_state
    symbol = req.symbol.upper().replace("/", "")
    target_tf = req.target_timeframe.lower().strip()
    storage_dir = app_state.state["configurations"]["storage_dir"]
    base_dir = os.path.join(storage_dir, "BINANCE", symbol)
    tfs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    base_tf = "5m" if "5m" in tfs else tfs[0]
    base_file = os.path.join(base_dir, base_tf, "ohlcv.h5")
    
    try:
        with HDF5Storage(base_file, "BINANCE", symbol, base_tf, mode='r', group_path="/OHLCV") as storage_base:
            full_data = storage_base.read_array(storage_base.dataset_path)
            
        base_cols = [n for n in OHLCV_DTYPE.names]
        ohlcv_data = full_data[base_cols].copy().astype(OHLCV_DTYPE)
        resampled_data = resample_ohlcv(ohlcv_data, target_tf, align='close')
        
        target_dir = os.path.join(storage_dir, "BINANCE", symbol, target_tf)
        os.makedirs(target_dir, exist_ok=True)
        target_file_path = os.path.join(target_dir, "ohlcv.h5")
        
        with HDF5Storage(target_file_path, "BINANCE", symbol, target_tf, mode='w', group_path="/OHLCV") as target_storage:
            target_storage.write_array(target_storage.dataset_path, resampled_data)
        
        conn = sqlite3.connect("data/runs.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM runs WHERE symbol = ? AND timeframe = ?", (symbol, target_tf))
        start_str = pd.to_datetime(full_data[0]['open_time'], unit='ms').strftime('%Y-%m-%d')
        end_str = pd.to_datetime(full_data[-1]['open_time'], unit='ms').strftime('%Y-%m-%d')
        cursor.execute("""
            INSERT INTO runs (symbol, timeframe, sample_size, period_start, period_end, kick_threshold, timestamp)
            VALUES (?, ?, ?, ?, ?, 2.0, datetime('now'))
        """, (symbol, target_tf, len(full_data), start_str, end_str))
        conn.commit()
        conn.close()
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, auto_compute_features, storage_dir, "BINANCE", symbol, target_tf)
        
        return {"status": "success", "timeframe_added": target_tf}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/refresh/{symbol}")
async def refresh_symbol_data(symbol: str):
    from backend.api.gateway import app_state, tasks_db, run_async_background_task
    symbol = symbol.upper().replace("/", "")
    storage_dir = app_state.state["configurations"]["storage_dir"]
    base_dir = os.path.join(storage_dir, "BINANCE", symbol)
    if not os.path.exists(base_dir):
        raise HTTPException(status_code=404, detail="Symbol introuvable localement.")
        
    async def do_refresh(task_id: str):
        from backend.api.gateway import app_state
        from backend.data.binance_client import BinanceClient
        loop = asyncio.get_running_loop()
        tf_dirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        
        async with BinanceClient() as client:
            for idx, tf in enumerate(tf_dirs):
                h5_file = os.path.join(base_dir, tf, "ohlcv.h5")
                last_time = -1
                if os.path.exists(h5_file):
                    with HDF5Storage(h5_file, "BINANCE", symbol, tf, mode='r', group_path="/OHLCV") as storage:
                        arr = storage.read_array(storage.dataset_path)
                        if len(arr) > 0:
                            last_time = arr[-1]['open_time']
                
                if last_time == -1:
                    continue
                    
                now_ms = int(time.time() * 1000)
                missing_data = await client.fetch_klines_historical(symbol=symbol, timeframe=tf, start_time=last_time + 1, end_time=now_ms)
                
                if len(missing_data) > 0:
                    with HDF5Storage(h5_file, "BINANCE", symbol, tf, mode='a', group_path="/OHLCV") as storage:
                        storage.append_chunk(missing_data)
                        
                await loop.run_in_executor(None, auto_compute_features, storage_dir, "BINANCE", symbol, tf)
                
        return {"symbol": symbol, "refreshed_timeframes": tf_dirs}
        
    task_id = run_async_background_task(do_refresh)
    return {"task_id": task_id, "status": "running"}