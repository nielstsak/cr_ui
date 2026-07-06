# FICHIER : backend/api/gateway.py
import asyncio
import io
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import uuid
import sys
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import pandas as pd
import pydantic
import uvicorn
import zmq
import vectorbtpro as vbt

from talib import abstract, get_function_groups 

from backend.core.resampler import timeframe_to_ms, resample_ohlcv
from backend.core.indicator_engine import auto_compute_features, BASE_COLS
from backend.data.binance_client import BinanceClient
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE
from backend.api.runs import router as runs_router, init_database_and_runs, sync_database_with_disk

logger = logging.getLogger("GatewayAPI")

def serialize_array(arr: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, arr)
    return buffer.getvalue()

def deserialize_array(data: bytes) -> np.ndarray:
    buffer = io.BytesIO(data)
    return np.load(buffer)

class ZMQBridgeServer(threading.Thread):
    def __init__(self, storage_dir: str = "data", host: str = "127.0.0.1", port: int = 5555):
        super().__init__()
        self.storage_dir = storage_dir
        self.host = host
        self.port = port
        self.running = False
        self.daemon = True

    def run(self):
        self.running = True
        context = zmq.Context()
        socket = context.socket(zmq.REP)
        socket.bind(f"tcp://{self.host}:{self.port}")
        socket.setsockopt(zmq.RCVTIMEO, 1000)

        while self.running:
            try:
                message = socket.recv_string()
                req = json.loads(message)
                action = req.get("action")

                if action == "load_data":
                    exchange = req.get("exchange", "BINANCE").upper()
                    symbol = req.get("symbol", "BTCUSDT").upper().replace("/", "")
                    target_timeframe = req.get("timeframe", "5m").lower()
                    start_time = int(req.get("start_time"))
                    end_time = int(req.get("end_time"))

                    file_path_target = os.path.join(self.storage_dir, exchange, symbol, target_timeframe, "ohlcv.h5")
                    if os.path.exists(file_path_target):
                        storage = HDF5Storage(file_path_target, exchange, symbol, target_timeframe, mode='r')
                        data = storage.read_chunk(start_time, end_time)
                        socket.send(serialize_array(data))
                        continue

                    base_timeframe = "5m"
                    file_path_base = os.path.join(self.storage_dir, exchange, symbol, base_timeframe, "ohlcv.h5")
                    
                    if not os.path.exists(file_path_base):
                        empty_arr = np.empty(0, dtype=OHLCV_DTYPE)
                        socket.send(serialize_array(empty_arr))
                        continue
                        
                    storage = HDF5Storage(file_path_base, exchange, symbol, base_timeframe, mode='r')
                    data = storage.read_chunk(start_time, end_time)
                    if target_timeframe != base_timeframe and len(data) > 0:
                        data = resample_ohlcv(data, target_timeframe, align='close')
                        
                    socket.send(serialize_array(data))
                else:
                    socket.send_string("ERROR: Action inconnue")
            except zmq.Again:
                continue
            except Exception as e:
                try: socket.send(serialize_array(np.empty(0, dtype=OHLCV_DTYPE)))
                except Exception: pass

        socket.close()
        context.term()

    def stop(self):
        self.running = False

def load_numpy_via_zmq(exchange: str, symbol: str, timeframe: str, start_time: int, end_time: int) -> np.ndarray:
    context = zmq.Context.instance()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, 5000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect("tcp://127.0.0.1:5555")

    try:
        req = {"action": "load_data", "exchange": exchange, "symbol": symbol, "timeframe": timeframe, "start_time": start_time, "end_time": end_time}
        socket.send_string(json.dumps(req))
        data_bytes = socket.recv()
        return deserialize_array(data_bytes)
    except Exception as e:
        file_path_target = os.path.join("data", exchange.upper(), symbol.upper().replace("/", ""), timeframe.lower(), "ohlcv.h5")
        if os.path.exists(file_path_target):
            with HDF5Storage(file_path_target, exchange, symbol, timeframe.lower(), mode='r') as storage:
                return storage.read_chunk(start_time, end_time)

        base_timeframe = "5m"
        file_path_base = os.path.join("data", exchange.upper(), symbol.upper().replace("/", ""), base_timeframe, "ohlcv.h5")
        if os.path.exists(file_path_base):
            with HDF5Storage(file_path_base, exchange, symbol, base_timeframe, mode='r') as storage:
                data = storage.read_chunk(start_time, end_time)
            if timeframe.lower() != base_timeframe and len(data) > 0:
                data = resample_ohlcv(data, timeframe.lower(), align='close')
            return data
        return np.empty(0, dtype=OHLCV_DTYPE)
    finally:
        socket.close()

class AppStateManager:
    def __init__(self, file_path: str = "app_state.json"):
        self.file_path = os.path.abspath(file_path)
        self.state = {
            "active_pairs": [],
            "configurations": { "initial_balance": 10000.0, "fee_rate": 0.0004, "slippage_rate": 0.0005, "mmr": 0.05, "leverage": 1.0, "storage_dir": "data" },
            "session": { "status": "online", "started_at": int(time.time()) }
        }
        self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    saved = json.load(f)
                    for k, v in saved.items():
                        if isinstance(v, dict) and k in self.state: self.state[k].update(v)
                        else: self.state[k] = v
            except Exception as e: pass

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e: pass

app_state = AppStateManager()

class WebSocketLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.connections: Set[WebSocket] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def emit(self, record):
        try:
            log_entry = self.format(record)
            if self.connections and self.loop:
                asyncio.run_coroutine_threadsafe(self.broadcast(log_entry), self.loop)
        except Exception: self.handleError(record)

    async def broadcast(self, message: str):
        disconnected = []
        for ws in list(self.connections):
            try: await ws.send_text(message)
            except Exception: disconnected.append(ws)
        for ws in disconnected: self.connections.discard(ws)

ws_log_handler = WebSocketLogHandler()
tasks_db = {} 

def run_async_background_task(coro_func, *args, **kwargs) -> str:
    task_id = str(uuid.uuid4())
    tasks_db[task_id] = { "status": "running", "progress": 0.0, "result": None, "error": None }
    async def wrapper():
        try:
            res = await coro_func(task_id, *args, **kwargs)
            tasks_db[task_id]["status"] = "completed"
            tasks_db[task_id]["progress"] = 100.0
            tasks_db[task_id]["result"] = res
        except asyncio.CancelledError:
            tasks_db[task_id]["status"] = "cancelled"
        except Exception as e:
            tasks_db[task_id]["status"] = "failed"
            tasks_db[task_id]["error"] = str(e)
    asyncio.create_task(wrapper())
    return task_id

app = FastAPI(title="TradingVBT Core API Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.include_router(runs_router)
zmq_server: Optional[ZMQBridgeServer] = None

@app.on_event("startup")
async def startup_event():
    global zmq_server
    loop = asyncio.get_running_loop()
    ws_log_handler.loop = loop
    ws_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logging.getLogger().addHandler(ws_log_handler)
    logging.getLogger().setLevel(logging.INFO)
    
    zmq_server = ZMQBridgeServer(storage_dir=app_state.state["configurations"]["storage_dir"])
    zmq_server.start()
    init_database_and_runs()
    sync_database_with_disk()

@app.on_event("shutdown")
async def shutdown_event():
    global zmq_server
    if zmq_server: zmq_server.stop()

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

class OhlcvDataRequest(pydantic.BaseModel):
    exchange: str = "BINANCE"
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    columns: Optional[List[str]] = None

class IndicatorApplyRequest(pydantic.BaseModel):
    symbol: str

async def _vbt_fetch_coro(task_id: str, req: VbtFetchRequest):
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
        with HDF5Storage(tf_file_path, "BINANCE", symbol, tf, mode='w') as tf_storage:
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
        
        # Exécution Fire-and-Forget pour ne pas bloquer le système si le calcul est lourd
        def safe_compute():
            try: auto_compute_features(storage_dir, "BINANCE", symbol, tf)
            except Exception as e: logger.error(f"Erreur background auto_compute: {e}")
        loop.run_in_executor(None, safe_compute)

        tasks_db[task_id]["progress"] = 100.0
        return {"symbol": symbol, "timeframe": tf, "candles": len(chunk)}
    except Exception as e:
        raise e
    finally:
        app_state.state["active_pairs"] = [p for p in app_state.state["active_pairs"] if p["symbol"] != symbol]
        app_state.save()

@app.post("/api/ingestion/vbt-fetch")
async def start_vbt_fetch(req: VbtFetchRequest):
    for p in app_state.state["active_pairs"]:
        if p["symbol"] == req.symbol.upper() and p["status"] == "ingesting":
            raise HTTPException(status_code=400, detail="Une ingestion est déjà en cours.")
    task_id = run_async_background_task(_vbt_fetch_coro, req=req)
    return {"task_id": task_id, "status": "running"}

@app.get("/api/ingestion/vbt-info/{symbol}")
async def get_vbt_info(symbol: str):
    symbol = symbol.upper().replace("/", "")
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol)
    if not os.path.exists(base_dir): raise HTTPException(status_code=404, detail="Introuvable.")
    try:
        tf_dirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        tf_dir = tf_dirs[0] 
        h5_file = os.path.join(base_dir, tf_dir, "ohlcv.h5")
        
        with HDF5Storage(h5_file, "BINANCE", symbol, tf_dir, mode='r') as storage:
            arr = storage.read_array(storage.dataset_path)
        
        df = pd.DataFrame(arr)
        indicators_found = set()
        for col in df.columns:
            if col not in BASE_COLS:
                base_name = col.split('_')[0]
                indicators_found.add(base_name)
                
        df.index = pd.to_datetime(df['open_time'], unit='ms')
        df = df.drop(columns=['open_time'])
        vbt_data = vbt.Data.from_data({symbol: df})
        
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

@app.get("/api/ingestion/status")
async def get_ingestion_status():
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

@app.get("/api/ingestion/stats/{symbol}")
async def get_symbol_descriptive_stats(symbol: str):
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
            with HDF5Storage(h5_file, "BINANCE", symbol, tf_dir, mode='r') as storage:
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

@app.delete("/api/ingestion/delete/{symbol}")
async def purge_symbol_data(symbol: str):
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

@app.post("/api/ingestion/add-timeframe")
async def add_timeframe_via_resampling(req: AddTimeframeRequest):
    symbol = req.symbol.upper().replace("/", "")
    target_tf = req.target_timeframe.lower().strip()
    storage_dir = app_state.state["configurations"]["storage_dir"]
    base_dir = os.path.join(storage_dir, "BINANCE", symbol)
    tfs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    base_tf = "5m" if "5m" in tfs else tfs[0]
    base_file = os.path.join(base_dir, base_tf, "ohlcv.h5")
    
    try:
        # === FIX CRITIQUE: Extraire unitairement les 8 colonnes OHLCV ===
        # L'ancienne version crashait car HDF5 renvoyait > 150 colonnes à Numba.
        with HDF5Storage(base_file, "BINANCE", symbol, base_tf, mode='r') as storage_base:
            full_data = storage_base.read_array(storage_base.dataset_path)
            
        base_cols = [n for n in OHLCV_DTYPE.names]
        ohlcv_data = full_data[base_cols].copy().astype(OHLCV_DTYPE)
        
        resampled_data = resample_ohlcv(ohlcv_data, target_tf, align='close')
        
        target_dir = os.path.join(storage_dir, "BINANCE", symbol, target_tf)
        os.makedirs(target_dir, exist_ok=True)
        target_file_path = os.path.join(target_dir, "ohlcv.h5")
        
        with HDF5Storage(target_file_path, "BINANCE", symbol, target_tf, mode='w') as target_storage:
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
        
        # Fire-And-Forget (évite le timeout HTTP 500)
        loop = asyncio.get_running_loop()
        def safe_compute():
            try: auto_compute_features(storage_dir, "BINANCE", symbol, target_tf)
            except Exception as e: logger.error(f"Erreur background auto_compute sur le resample: {e}")
        loop.run_in_executor(None, safe_compute)
        
        return {"status": "success", "timeframe_added": target_tf}
    except Exception as e:
        logger.error(f"Add Timeframe Erreur 500 : {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks_db: raise HTTPException(status_code=404, detail="Task introuvable.")
    return tasks_db[task_id]

@app.get("/api/indicators/groups")
async def get_indicator_groups():
    return get_function_groups()

@app.post("/api/data/ohlcv")
async def get_ohlcv_data(req: OhlcvDataRequest):
    arr = load_numpy_via_zmq(req.exchange, req.symbol, req.timeframe, req.start_time, req.end_time)
    if len(arr) == 0:
        raise HTTPException(status_code=400, detail="No historical prices available.")
    
    df = pd.DataFrame(arr)
    
    # === SÉLECTION STRICTE (Protège la bande passante HTTP) ===
    cols_to_keep = ['open_time', 'open', 'high', 'low', 'close', 'volume']
    if req.columns:
        cols_to_keep.extend([c for c in req.columns if c in df.columns])
    
    cols_to_keep = list(dict.fromkeys(cols_to_keep))
    df = df[cols_to_keep]

    # === DÉCIMATION CONTINUE (Empêche Plotly de geler / les gaps visuels massifs) ===
    MAX_POINTS = 2000
    if len(df) > MAX_POINTS:
        df = df.tail(MAX_POINTS).copy()
        
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df = df.astype(object).where(pd.notnull(df), None)
    
    return df.to_dict(orient="list")

@app.post("/api/indicators/apply")
async def apply_indicators_to_hdf5(req: IndicatorApplyRequest):
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
        logger.error(f"Erreur application indicateurs : {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/indicator/metadata/{func_name}")
async def get_indicator_metadata(func_name: str):
    try:
        ind_func = abstract.Function(func_name.upper())
        return {
            "name": ind_func.info.get("name", func_name.upper()),
            "outputs": list(ind_func.info.get("output_names", []))
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.websocket("/api/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_log_handler.connections.add(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        ws_log_handler.connections.remove(websocket)

if __name__ == "__main__":
    uvicorn.run("backend.api.gateway:app", host="0.0.0.0", port=8000, reload=True)