import asyncio
import io
import json
import logging
import os
import threading
import time
import uuid
from typing import Dict, List, Optional, Set, Tuple

import fastapi
from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import pandas as pd
import pydantic
import uvicorn
import zmq
import talib

from backend.core.indicators import DynamicIndicatorFactory, get_talib_metadata, get_ui_parameter_schema
from backend.core.resampler import timeframe_to_ms, resample_ohlcv
from backend.data.binance_client import BinanceClient
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE
from backend.ml.wfo import check_robustness, generate_wfo_splits, optimize_segment, stitch_oos_performance
from backend.simulation.margin_portfolio import simulate_margin_portfolio
from backend.api.routers.runs import router as runs_router, init_database_and_runs, sync_database_with_disk
from backend.ml.analysis_engine import (
    compute_base_features,
    detect_kicks,
    compute_directional_transitions,
    compute_conditional_probabilities,
    compute_hmm_regimes,
    compute_pca_clusters
)

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
        logger.info(f"ZMQBridgeServer started on tcp://{self.host}:{self.port}")

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

                    base_timeframe = "5m"
                    file_path = os.path.join(self.storage_dir, exchange, symbol, base_timeframe, "ohlcv.h5")
                    
                    if not os.path.exists(file_path):
                        empty_arr = np.empty(0, dtype=OHLCV_DTYPE)
                        socket.send(serialize_array(empty_arr))
                        continue
                        
                    storage = HDF5Storage(file_path, exchange, symbol, base_timeframe)
                    data = storage.read_chunk(start_time, end_time)
                    
                    if target_timeframe != base_timeframe and len(data) > 0:
                        data = resample_ohlcv(data, target_timeframe, align='close')
                        
                    socket.send(serialize_array(data))
                else:
                    socket.send_string("ERROR: Unknown request action")
            except zmq.Again:
                continue
            except Exception as e:
                logger.error(f"Error in ZMQ Server execution: {e}")
                try:
                    empty_arr = np.empty(0, dtype=OHLCV_DTYPE)
                    socket.send(serialize_array(empty_arr))
                except Exception:
                    pass

        socket.close()
        context.term()
        logger.info("ZMQBridgeServer stopped.")

    def stop(self):
        self.running = False


def load_numpy_via_zmq(exchange: str, symbol: str, timeframe: str, start_time: int, end_time: int) -> np.ndarray:
    context = zmq.Context.instance()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, 5000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect("tcp://127.0.0.1:5555")

    try:
        req = {
            "action": "load_data",
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "start_time": start_time,
            "end_time": end_time
        }
        socket.send_string(json.dumps(req))
        data_bytes = socket.recv()
        return deserialize_array(data_bytes)
    except Exception as e:
        logger.warning(f"ZMQ Bridge query failed: {e}. Falling back to direct HDF5 storage read.")
        base_timeframe = "5m"
        file_path = os.path.join("data", exchange.upper(), symbol.upper().replace("/", ""), base_timeframe, "ohlcv.h5")
        if os.path.exists(file_path):
            storage = HDF5Storage(file_path, exchange, symbol, base_timeframe)
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
            "configurations": {
                "initial_balance": 10000.0,
                "fee_rate": 0.0004,
                "slippage_rate": 0.0005,
                "mmr": 0.05,
                "leverage": 1.0,
                "storage_dir": "data"
            },
            "session": {
                "status": "online",
                "started_at": int(time.time())
            }
        }
        self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    saved = json.load(f)
                    for k, v in saved.items():
                        if isinstance(v, dict) and k in self.state:
                            self.state[k].update(v)
                        else:
                            self.state[k] = v
            except Exception as e:
                logger.error(f"Error loading state JSON: {e}")

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            logger.error(f"Error writing state JSON: {e}")


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
        except Exception:
            self.handleError(record)

    async def broadcast(self, message: str):
        disconnected = []
        for ws in list(self.connections):
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.connections.discard(ws)


ws_log_handler = WebSocketLogHandler()

tasks_db = {} 


def run_async_background_task(coro_func, *args, **kwargs) -> str:
    task_id = str(uuid.uuid4())
    tasks_db[task_id] = {
        "status": "running",
        "progress": 0.0,
        "result": None,
        "error": None
    }

    async def wrapper():
        try:
            res = await coro_func(task_id, *args, **kwargs)
            tasks_db[task_id]["status"] = "completed"
            tasks_db[task_id]["progress"] = 100.0
            tasks_db[task_id]["result"] = res
        except asyncio.CancelledError:
            tasks_db[task_id]["status"] = "cancelled"
        except Exception as e:
            logger.error(f"Background task {task_id} failed: {e}")
            tasks_db[task_id]["status"] = "failed"
            tasks_db[task_id]["error"] = str(e)

    asyncio.create_task(wrapper())
    return task_id


app = FastAPI(title="TradingVBT Core API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router)

zmq_server: Optional[ZMQBridgeServer] = None


@app.on_event("startup")
async def startup_event():
    global zmq_server
    loop = asyncio.get_running_loop()
    
    ws_log_handler.loop = loop
    ws_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    logging.getLogger().addHandler(ws_log_handler)
    logging.getLogger().setLevel(logging.INFO)
    
    zmq_server = ZMQBridgeServer(storage_dir=app_state.state["configurations"]["storage_dir"])
    zmq_server.start()

    init_database_and_runs()
    sync_database_with_disk()
    
    logger.info("Lifespan setup completed.")


@app.on_event("shutdown")
async def shutdown_event():
    global zmq_server
    if zmq_server:
        zmq_server.stop()
    logger.info("Application shutdown completed.")


class IngestionRequest(pydantic.BaseModel):
    symbol: str
    timeframe: str
    days_history: int = 30


class IndicatorCalculateRequest(pydantic.BaseModel):
    func_name: str
    exchange: str = "BINANCE"
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    params: dict = {}
    downcast_float32: bool = False


class SimulationRunRequest(pydantic.BaseModel):
    exchange: str = "BINANCE"
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    signals: List[int]
    initial_balance: float = 10000.0
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0005
    mmr: float = 0.05
    leverage: float = 1.0


class OptimizationRequest(pydantic.BaseModel):
    exchange: str = "BINANCE"
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    n_splits: int = 5
    train_ratio: float = 0.8
    embargo: int = 20
    n_trials: int = 30
    strategy_name: str = "SMA_Crossover" 
    initial_balance: float = 10000.0
    mmr: float = 0.05
    leverage: float = 2.0


class AnalysisRequest(pydantic.BaseModel):
    exchange: str = "BINANCE"
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    kick_threshold_pct: float = 2.0


async def _ingestion_coro(task_id: str, symbol: str, timeframe: str, days_history: int):
    if timeframe.lower() != "5m":
        logger.info(f"Timeframe {timeframe} ignoré pour l'ingestion. Forcé à 5m (Source de vérité).")
        timeframe = "5m"

    end_time = int(time.time() * 1000)
    start_time = end_time - days_history * 24 * 3600 * 1000
    tf_ms = timeframe_to_ms(timeframe)
    total_expected_candles = (end_time - start_time) // tf_ms

    pair_record = {"symbol": symbol.upper(), "timeframe": timeframe.lower(), "status": "ingesting", "task_id": task_id}
    app_state.state["active_pairs"].append(pair_record)
    app_state.save()

    try:
        file_path = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol.upper(), timeframe.lower(), "ohlcv.h5")
        storage = HDF5Storage(file_path, "BINANCE", symbol, timeframe)
        
        async with BinanceClient() as client:
            current_start = start_time
            candles_fetched = 0
            
            while current_start <= end_time:
                chunk = await client.fetch_klines_historical(symbol, timeframe, current_start, end_time)
                if len(chunk) == 0:
                    break
                    
                storage.append_chunk(chunk)
                candles_fetched += len(chunk)
                
                progress = min(99.9, (candles_fetched / max(1, total_expected_candles)) * 100.0)
                tasks_db[task_id]["progress"] = round(progress, 1)
                
                last_open = chunk[-1]['open_time']
                current_start = last_open + 1
                if last_open >= end_time:
                    break
                    
        return {"candles_fetched": candles_fetched}
    finally:
        for p in app_state.state["active_pairs"]:
            if p["symbol"] == symbol.upper() and p["timeframe"] == timeframe.lower():
                p["status"] = "idle"
        app_state.save()


@app.post("/api/ingestion/start")
async def start_ingestion(req: IngestionRequest):
    for p in app_state.state["active_pairs"]:
        if p["symbol"] == req.symbol.upper() and p["timeframe"] == "5m" and p["status"] == "ingesting":
            raise HTTPException(status_code=400, detail="Ingestion task already running for this symbol.")
            
    task_id = run_async_background_task(
        _ingestion_coro,
        symbol=req.symbol,
        timeframe="5m",
        days_history=req.days_history
    )
    return {"task_id": task_id, "status": "running"}


@app.get("/api/ingestion/status")
async def get_ingestion_status():
    return {"active_pairs": app_state.state["active_pairs"]}


@app.get("/api/indicator/metadata/{func_name}")
async def get_indicator_metadata(func_name: str):
    try:
        return get_talib_metadata(func_name.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/indicator/schema/{func_name}")
async def get_indicator_schema(func_name: str):
    try:
        return get_ui_parameter_schema(func_name.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/indicator/calculate")
async def calculate_indicator(req: IndicatorCalculateRequest):
    arr = load_numpy_via_zmq(req.exchange, req.symbol, req.timeframe, req.start_time, req.end_time)
    
    if len(arr) == 0:
        raise HTTPException(status_code=400, detail="No historical data loaded for indicator inputs.")
        
    inputs = {
        'open': arr['open'],
        'high': arr['high'],
        'low': arr['low'],
        'close': arr['close'],
        'volume': arr['volume']
    }
    
    try:
        res = DynamicIndicatorFactory.run_indicator(
            func_name=req.func_name.upper(),
            inputs=inputs,
            params=req.params,
            downcast_float32=req.downcast_float32
        )
        serializable_outputs = {}
        for k, v in res["outputs"].items():
            clean_v = np.where(np.isnan(v) | np.isinf(v), None, v)
            serializable_outputs[k] = clean_v.tolist()
        return {
            "outputs": serializable_outputs,
            "columns": res["columns"]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Indicator run error: {e}")


@app.post("/api/simulation/run")
async def run_simulation(req: SimulationRunRequest):
    arr = load_numpy_via_zmq(req.exchange, req.symbol, req.timeframe, req.start_time, req.end_time)
    if len(arr) == 0:
        raise HTTPException(status_code=400, detail="No historical prices available for backtest.")
        
    close = arr['close']
    signals = np.array(req.signals, dtype=np.int32)
    
    if len(signals) != len(close):
        raise HTTPException(
            status_code=400,
            detail=f"Signals vector length mismatch. Expected {len(close)}, got {len(signals)}."
        )
        
    try:
        tf_ms = timeframe_to_ms(req.timeframe)
        annualization_factor = (365.25 * 24.0 * 3600.0 * 1000.0) / tf_ms
        
        stats = simulate_margin_portfolio(
            close=close,
            signals=signals,
            initial_balance=req.initial_balance,
            fee_rate=req.fee_rate,
            slippage_rate=req.slippage_rate,
            mmr=req.mmr,
            leverage=req.leverage,
            annualization_factor=annualization_factor
        )
        
        return {
            "total_return": stats["total_return"],
            "annualized_return": stats["annualized_return"],
            "max_drawdown": stats["max_drawdown"],
            "downside_deviation": stats["downside_deviation"],
            "sortino_ratio": stats["sortino_ratio"],
            "composite_score": stats["composite_score"],
            "series": {
                "equity": stats["equity"].tolist(),
                "balance": stats["balance"].tolist(),
                "position": stats["position"].tolist(),
                "entry_price": stats["entry_price"].tolist(),
                "liquidation": stats["liquidation"].tolist()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Backtest simulation execution failed: {e}")


@app.post("/api/analysis/compute")
async def compute_analysis(req: AnalysisRequest):
    arr = load_numpy_via_zmq(req.exchange, req.symbol, req.timeframe, req.start_time, req.end_time)
    if len(arr) == 0:
        raise HTTPException(status_code=400, detail="No historical prices available for analysis.")
    
    try:
        df = pd.DataFrame(arr)
        
        df = compute_base_features(df)
        df = detect_kicks(df, req.kick_threshold_pct)
        df = compute_hmm_regimes(df)
        
        transitions = compute_directional_transitions(df)
        probs = compute_conditional_probabilities(df)
        pca_clusters = compute_pca_clusters(df)
        
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df = df.where(pd.notnull(df), None)
        
        return {
            "directional_transitions": transitions,
            "conditional_probabilities": probs,
            "pca_clusters": pca_clusters,
            "timeseries": df.to_dict(orient="list")
        }
    except Exception as e:
        logger.error(f"Analysis computation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis computation failed: {str(e)}")


def _wfo_sma_signals_gen(close: np.ndarray, params: dict) -> np.ndarray:
    fast = int(params.get('fast', 10))
    slow = int(params.get('slow', 30))
    n = len(close)
    signals = np.zeros(n, dtype=np.int32)
    if n < slow:
        return signals
        
    sma_fast = talib.SMA(close, timeperiod=fast)
    sma_slow = talib.SMA(close, timeperiod=slow)
    
    for i in range(slow, n):
        if sma_fast[i] > sma_slow[i]:
            signals[i] = 1
        elif sma_fast[i] < sma_slow[i]:
            signals[i] = -1
    return signals


def _wfo_rsi_signals_gen(close: np.ndarray, params: dict) -> np.ndarray:
    period = int(params.get('timeperiod', 14))
    lower = float(params.get('lower_barrier', 30.0))
    upper = float(params.get('upper_barrier', 70.0))
    n = len(close)
    signals = np.zeros(n, dtype=np.int32)
    if n < period:
        return signals
        
    rsi = talib.RSI(close, timeperiod=period)
    
    curr_state = 0
    for i in range(period, n):
        if rsi[i] < lower:
            curr_state = 1
        elif rsi[i] > upper:
            curr_state = -1
        signals[i] = curr_state
    return signals


async def _wfo_optimization_task(task_id: str, req: OptimizationRequest):
    arr = load_numpy_via_zmq(req.exchange, req.symbol, req.timeframe, req.start_time, req.end_time)
    if len(arr) == 0:
        raise ValueError("No historical price array returned by ZMQ database bridge.")
        
    close = arr['close']
    n_len = len(close)
    
    splits = generate_wfo_splits(n_len, req.n_splits, req.train_ratio, req.embargo)
    
    if req.strategy_name == "SMA_Crossover":
        signals_gen = _wfo_sma_signals_gen
        def param_space(trial):
            fast = trial.suggest_int('fast', 2, 20)
            slow = trial.suggest_int('slow', 21, 60)
            return {'fast': fast, 'slow': slow}
    elif req.strategy_name == "RSI_Crossover":
        signals_gen = _wfo_rsi_signals_gen
        def param_space(trial):
            timeperiod = trial.suggest_int('timeperiod', 2, 30)
            lower = trial.suggest_float('lower_barrier', 10.0, 45.0)
            upper = trial.suggest_float('upper_barrier', 55.0, 90.0)
            return {'timeperiod': timeperiod, 'lower_barrier': lower, 'upper_barrier': upper}
    else:
        raise ValueError(f"Strategy '{req.strategy_name}' is not supported.")
        
    tf_ms = timeframe_to_ms(req.timeframe)
    annualization_factor = (365.25 * 24.0 * 3600.0 * 1000.0) / tf_ms
    
    oos_equities = []
    splits_results = []
    
    step_percent = 100.0 / req.n_splits
    
    for split_idx, s in enumerate(splits):
        train_start, train_end = s['train']
        test_start, test_end = s['test']
        
        close_train = close[train_start:train_end]
        close_test = close[test_start:test_end]
        
        logger.info(f"Optimizing split {split_idx+1}/{req.n_splits} IS range [{train_start}:{train_end}]...")
        
        opt_res = optimize_segment(
            close_train=close_train,
            signals_gen_func=signals_gen,
            param_space_func=param_space,
            initial_balance=req.initial_balance,
            mmr=req.mmr,
            leverage=req.leverage,
            n_trials=req.n_trials,
            annualization_factor=annualization_factor
        )
        
        best_params = opt_res["best_params"]
        
        is_signals = signals_gen(close_train, best_params)
        is_stats = simulate_margin_portfolio(
            close=close_train,
            signals=is_signals,
            initial_balance=req.initial_balance,
            fee_rate=0.0004,
            slippage_rate=0.0005,
            mmr=req.mmr,
            leverage=req.leverage,
            annualization_factor=annualization_factor
        )
        
        oos_signals = signals_gen(close_test, best_params)
        oos_stats = simulate_margin_portfolio(
            close=close_test,
            signals=oos_signals,
            initial_balance=req.initial_balance,
            fee_rate=0.0004,
            slippage_rate=0.0005,
            mmr=req.mmr,
            leverage=req.leverage,
            annualization_factor=annualization_factor
        )
        
        ri, is_valid = check_robustness(is_stats, oos_stats, tolerated_drawdown=0.20)
        
        oos_equities.append(oos_stats["equity"])
        
        splits_results.append({
            "split_index": split_idx,
            "train_range": [train_start, train_end],
            "test_range": [test_start, test_end],
            "best_params": best_params,
            "robustness_index": ri,
            "is_valid": is_valid,
            "is_return": is_stats["total_return"],
            "oos_return": oos_stats["total_return"]
        })
        
        tasks_db[task_id]["progress"] = round((split_idx + 1) * step_percent, 1)
        
    stitched_equity = stitch_oos_performance(oos_equities, initial_balance=req.initial_balance)
    
    tot_ret = (stitched_equity[-1] - req.initial_balance) / req.initial_balance
    
    return {
        "splits": splits_results,
        "stitched_equity": stitched_equity.tolist(),
        "total_stitched_return": tot_ret
    }


@app.post("/api/simulation/optimize")
async def optimize_wfo(req: OptimizationRequest):
    task_id = run_async_background_task(_wfo_optimization_task, req=req)
    return {"task_id": task_id, "status": "running"}


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="Task ID not found in cache.")
    return tasks_db[task_id]


@app.websocket("/api/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    if ws_log_handler:
        ws_log_handler.connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws_log_handler:
            ws_log_handler.connections.discard(websocket)