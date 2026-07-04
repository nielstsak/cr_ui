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
from backend.api.runs import router as runs_router, init_database_and_runs, sync_database_with_disk
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
    """
    Serveur d'échange IPC basé sur ZeroMQ. Permet de charger des matrices
    OHLCV partagées en mémoire vive ou stockées au format HDF5.
    """
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
        logger.info(f"ZMQBridgeServer démarré sur tcp://{self.host}:{self.port}")

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
                    socket.send_string("ERROR: Action inconnue")
            except zmq.Again:
                continue
            except Exception as e:
                logger.error(f"Erreur d'exécution ZMQ Bridge : {e}")
                try:
                    empty_arr = np.empty(0, dtype=OHLCV_DTYPE)
                    socket.send(serialize_array(empty_arr))
                except Exception:
                    pass

        socket.close()
        context.term()

    def stop(self):
        self.running = False


def load_numpy_via_zmq(exchange: str, symbol: str, timeframe: str, start_time: int, end_time: int) -> np.ndarray:
    """
    Query cliente IPC pour charger des données de trading via le canal ZMQ local.
    """
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
        logger.warning(f"ZMQ Bridge inaccessible : {e}. Utilisation du fallback HDF5 natif.")
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
    """
    Sauvegarde l'état courant de l'application et les configurations globales de l'utilisateur.
    """
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
                logger.error(f"Erreur de lecture de l'état JSON : {e}")

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            logger.error(f"Erreur d'écriture d'état : {e}")


app_state = AppStateManager()


class WebSocketLogHandler(logging.Handler):
    """
    Handler de logs asynchrone interceptant la sortie standard
    pour la diffuser en streaming sur l'interface utilisateur via WebSockets.
    """
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
    """
    Démarre et enregistre une tâche asynchrone non-bloquante avec suivi de progression.
    """
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
            logger.error(f"La tâche en arrière-plan {task_id} a échoué : {e}")
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
    ws_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logging.getLogger().addHandler(ws_log_handler)
    logging.getLogger().setLevel(logging.INFO)
    
    zmq_server = ZMQBridgeServer(storage_dir=app_state.state["configurations"]["storage_dir"])
    zmq_server.start()

    init_database_and_runs()
    sync_database_with_disk()
    logger.info("Gateway API Core initialisé avec succès.")


@app.on_event("shutdown")
async def shutdown_event():
    global zmq_server
    if zmq_server:
        zmq_server.stop()
    logger.info("Gateway API Core arrêté.")


# ==========================================
# DESCRIPTIVE MODELS & REQUEST SCHEMAS
# ==========================================

class IngestionRequest(pydantic.BaseModel):
    symbol: str
    timeframe: str
    days_history: int = 30


class MTFIngestionRequest(pydantic.BaseModel):
    symbol: str
    timeframes: List[str]
    days_history: int = 30


class AddTimeframeRequest(pydantic.BaseModel):
    symbol: str
    target_timeframe: str


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


# ==========================================
# SYSTEM WORKER: MULTI-TIMEFRAME PIPELINE
# ==========================================

async def _mtf_ingestion_coro(task_id: str, symbol: str, timeframes: List[str], days_history: int):
    """
    Exécute de manière transactionnelle l'ingestion multitemporelle (MTF).
    Télécharge TOUJOURS la granularité la plus fine (5m), puis exécute le resampling
    Numba JIT parallèle pour créer l'ensemble des timeframes cibles.
    """
    symbol = symbol.upper().replace("/", "")
    base_timeframe = "5m"
    
    # Validation / dédoublonnage des timeframes cibles
    timeframes = list(set([tf.lower().strip() for tf in timeframes]))
    if base_timeframe not in timeframes:
        timeframes.append(base_timeframe)
        
    end_time = int(time.time() * 1000)
    start_time = end_time - days_history * 24 * 3600 * 1000
    tf_ms = timeframe_to_ms(base_timeframe)
    total_expected_candles = (end_time - start_time) // tf_ms

    pair_record = {"symbol": symbol, "timeframe": "MTF", "status": "ingesting", "task_id": task_id}
    app_state.state["active_pairs"].append(pair_record)
    app_state.save()

    try:
        # Étape 1 : Téléchargement de la base de vérité (5m)
        base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol, base_timeframe)
        os.makedirs(base_dir, exist_ok=True)
        file_path_5m = os.path.join(base_dir, "ohlcv.h5")
        
        storage_5m = HDF5Storage(file_path_5m, "BINANCE", symbol, base_timeframe)
        
        logger.info(f"Démarrage de l'acquisition réseau : {symbol} {base_timeframe}")
        
        async with BinanceClient() as client:
            current_start = start_time
            candles_fetched = 0
            
            while current_start <= end_time:
                chunk = await client.fetch_klines_historical(symbol, base_timeframe, current_start, end_time)
                if len(chunk) == 0:
                    break
                    
                storage_5m.append_chunk(chunk)
                candles_fetched += len(chunk)
                
                # Progression plafonnée à 75% pour l'acquisition réseau
                progress = min(75.0, (candles_fetched / max(1, total_expected_candles)) * 75.0)
                tasks_db[task_id]["progress"] = round(progress, 1)
                
                last_open = chunk[-1]['open_time']
                current_start = last_open + 1
                if last_open >= end_time:
                    break
                    
        # Chargement de la source brute pour génération locale
        base_data = storage_5m.read_chunk(start_time, end_time)
        if len(base_data) == 0:
            raise ValueError(f"Le timeframe source (5m) pour {symbol} est vide.")

        # Étape 2 : Resampling et écriture des échelles demandées (75% à 95%)
        step_increment = 20.0 / max(1, len(timeframes))
        
        for idx, tf in enumerate(timeframes):
            if tf == base_timeframe:
                continue
                
            logger.info(f"Génération dynamique par resampling Numba JIT : {tf}")
            resampled_data = resample_ohlcv(base_data, tf, align='close')
            
            tf_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol, tf)
            os.makedirs(tf_dir, exist_ok=True)
            tf_file_path = os.path.join(tf_dir, "ohlcv.h5")
            
            tf_storage = HDF5Storage(tf_file_path, "BINANCE", symbol, tf)
            tf_storage.write_array(tf_storage.dataset_path, resampled_data)
            
            tasks_db[task_id]["progress"] = round(75.0 + (idx + 1) * step_increment, 1)

        # Étape 3 : Synchronisation SQL unifiée (runs.db)
        logger.info(f"Mise à jour des tables d'index SQL de session (runs.db)")
        conn = sqlite3.connect("data/runs.db")
        cursor = conn.cursor()
        
        # Effacer les anciennes configurations pour éviter des duplications de clés
        cursor.execute("DELETE FROM runs WHERE symbol = ?", (symbol,))
        
        start_str = pd.to_datetime(base_data[0]['open_time'], unit='ms').strftime('%Y-%m-%d')
        end_str = pd.to_datetime(base_data[-1]['open_time'], unit='ms').strftime('%Y-%m-%d')
        
        for tf in timeframes:
            cursor.execute("""
                INSERT INTO runs (symbol, timeframe, sample_size, period_start, period_end, kick_threshold, timestamp)
                VALUES (?, ?, ?, ?, ?, 2.0, datetime('now'))
            """, (symbol, tf, len(base_data), start_str, end_str))
            
        conn.commit()
        conn.close()

        tasks_db[task_id]["progress"] = 100.0
        logger.info(f"Pipeline d'ingestion unifiée MTF terminé pour {symbol}.")
        return {"symbol": symbol, "timeframes_completed": timeframes, "candles_ingested": len(base_data)}
        
    except Exception as e:
        logger.error(f"Échec de l'acquisition MTF : {str(e)}")
        raise e
    finally:
        app_state.state["active_pairs"] = [
            p for p in app_state.state["active_pairs"] if p["symbol"] != symbol
        ]
        app_state.save()


# ==========================================
# GATEWAY ROUTERS & ENDPOINTS
# ==========================================

@app.post("/api/ingestion/start-mtf")
async def start_mtf_ingestion(req: MTFIngestionRequest):
    """
    Lance une tâche d'acquisition et de rééchantillonnage de paires MTF en arrière-plan.
    """
    # Vérification qu'aucune tâche n'est déjà en cours sur cette paire
    for p in app_state.state["active_pairs"]:
        if p["symbol"] == req.symbol.upper() and p["status"] == "ingesting":
            raise HTTPException(status_code=400, detail="Une ingestion est déjà en cours pour ce symbole.")
            
    task_id = run_async_background_task(
        _mtf_ingestion_coro,
        symbol=req.symbol.upper(),
        timeframes=req.timeframes,
        days_history=req.days_history
    )
    return {"task_id": task_id, "status": "running"}


@app.get("/api/ingestion/stats/{symbol}")
async def get_symbol_descriptive_stats(symbol: str):
    symbol = symbol.upper().replace("/", "")
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol)
    
    if not os.path.exists(base_dir):
        return {} # Renvoie un dictionnaire vide conforme pour le store front-end
        
    stats = {}
    
    for tf_dir in os.listdir(base_dir):
        tf_path = os.path.join(base_dir, tf_dir)
        if not os.path.isdir(tf_path):
            continue
            
        h5_file = os.path.join(tf_path, "ohlcv.h5")
        if not os.path.exists(h5_file):
            continue
            
        try:
            storage = HDF5Storage(h5_file, "BINANCE", symbol, tf_dir)
            data = storage.read_array(storage.dataset_path)
            
            if len(data) == 0:
                continue
                
            closes = data['close']
            opens = data['open']
            highs = data['high']
            lows = data['low']
            volumes = data['volume']
            
            green_count = int(np.sum(closes > opens))
            red_count = int(np.sum(closes < opens))
            min_p = float(np.min(lows))
            max_p = float(np.max(highs))
            
            # Formule mathématique du Hold Ratio : (Pn - P0) / P0
            hold_ratio = float((closes[-1] - opens[0]) / opens[0] * 100)
            avg_vol = float(np.mean(volumes))
            
            # Calcul vectoriel causal du ratio d'absorption des mèches (Wick analysis)
            upper_wicks = (highs - np.maximum(opens, closes)) / closes
            lower_wicks = (np.minimum(opens, closes) - lows) / closes
            avg_upper_wick = float(np.mean(upper_wicks) * 100)
            avg_lower_wick = float(np.mean(lower_wicks) * 100)
            
            stats[tf_dir] = {
                "klines": len(data),
                "start_date": pd.to_datetime(data[0]['open_time'], unit='ms').strftime('%Y-%m-%d %H:%M'),
                "end_date": pd.to_datetime(data[-1]['open_time'], unit='ms').strftime('%Y-%m-%d %H:%M'),
                "green_count": green_count,
                "red_count": red_count,
                "min_price": round(min_p, 4),
                "max_price": round(max_p, 4),
                "hold_ratio_pct": round(hold_ratio, 2),
                "avg_volume": round(avg_vol, 2),
                "avg_upper_wick_pct": round(avg_upper_wick, 3),
                "avg_lower_wick_pct": round(avg_lower_wick, 3)
            }
        except Exception as e:
            logger.error(f"Erreur d'analyse sur {symbol} ({tf_dir}) : {e}")
            continue
            
    return stats


@app.delete("/api/ingestion/delete/{symbol}")
async def purge_symbol_data(symbol: str):
    """
    Purge l'intégralité des données physiques d'un symbole sur disque ainsi
    que ses sessions associées en base SQLite.
    """
    symbol = symbol.upper().replace("/", "")
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol)
    
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)
        logger.info(f"Répertoire physique de données détruit : {base_dir}")
        
    # Transaction de suppression SQL
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM runs WHERE symbol = ?", (symbol,))
    conn.commit()
    conn.close()
    
    sync_database_with_disk()
    return {"status": "success", "message": f"Purge complète effectuée pour {symbol}."}


@app.post("/api/ingestion/add-timeframe")
async def add_timeframe_via_resampling(req: AddTimeframeRequest):
    """
    Génère dynamiquement une unité de temps manquante par resampling direct
    depuis la base historique 5m de l'actif, évitant de nouvelles requêtes API.
    """
    symbol = req.symbol.upper().replace("/", "")
    target_tf = req.target_timeframe.lower().strip()
    
    base_file = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol, "5m", "ohlcv.h5")
    if not os.path.exists(base_file):
        raise HTTPException(status_code=404, detail="La source de vérité minimale (5m) doit être disponible.")
        
    try:
        storage_5m = HDF5Storage(base_file, "BINANCE", symbol, "5m")
        base_data = storage_5m.read_array(storage_5m.dataset_path)
        
        # Exécution du rééchantillonnage de précision
        resampled_data = resample_ohlcv(base_data, target_tf, align='close')
        
        # Structuration du répertoire de destination
        target_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol, target_tf)
        os.makedirs(target_dir, exist_ok=True)
        target_file_path = os.path.join(target_dir, "ohlcv.h5")
        
        target_storage = HDF5Storage(target_file_path, "BINANCE", symbol, target_tf)
        target_storage.write_array(target_storage.dataset_path, resampled_data)
        
        # Écriture de la nouvelle session run
        conn = sqlite3.connect("data/runs.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM runs WHERE symbol = ? AND timeframe = ?", (symbol, target_tf))
        
        start_str = pd.to_datetime(base_data[0]['open_time'], unit='ms').strftime('%Y-%m-%d')
        end_str = pd.to_datetime(base_data[-1]['open_time'], unit='ms').strftime('%Y-%m-%d')
        
        cursor.execute("""
            INSERT INTO runs (symbol, timeframe, sample_size, period_start, period_end, kick_threshold, timestamp)
            VALUES (?, ?, ?, ?, ?, 2.0, datetime('now'))
        """, (symbol, target_tf, len(base_data), start_str, end_str))
        
        conn.commit()
        conn.close()
        
        return {"status": "success", "timeframe_added": target_tf}
    except Exception as e:
        logger.error(f"Impossible de générer le timeframe {target_tf} : {e}")
        raise HTTPException(status_code=500, detail=f"Erreur de resampling interne : {str(e)}")


@app.post("/api/ingestion/refresh/{symbol}")
async def refresh_all_symbol_timeframes(symbol: str):
    """
    Détermine les échelles de temps actuellement générées localement
    pour cet actif et relance une synchronisation unifiée automatique.
    """
    symbol = symbol.upper().replace("/", "")
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE", symbol)
    
    if not os.path.exists(base_dir):
        raise HTTPException(status_code=404, detail=f"Aucune base historique trouvée pour {symbol}.")
        
    local_tfs = [name for name in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, name))]
    if "5m" not in local_tfs:
        local_tfs.append("5m")
        
    # Relancer l'acquisition sur l'historique standard
    task_id = run_async_background_task(
        _mtf_ingestion_coro,
        symbol=symbol,
        timeframes=local_tfs,
        days_history=30
    )
    return {"status": "success", "task_id": task_id}


@app.get("/api/ingestion/status")
async def get_ingestion_status():
    """
    Retourne la liste complète des symboles présents localement
    avec leurs statuts de traitement respectifs.
    """
    base_dir = os.path.join(app_state.state["configurations"]["storage_dir"], "BINANCE")
    local_symbols = []
    
    if os.path.exists(base_dir):
        for name in os.listdir(base_dir):
            sym_dir = os.path.join(base_dir, name)
            if os.path.isdir(sym_dir):
                timeframes = os.listdir(sym_dir)
                local_symbols.append({
                    "symbol": name,
                    "status": "idle",
                    "timeframe": ", ".join(timeframes)
                })
                
    # Fusionner avec les tâches réseau en cours
    for active in app_state.state["active_pairs"]:
        found = False
        for sym in local_symbols:
            if sym["symbol"] == active["symbol"]:
                sym["status"] = "ingesting"
                found = True
        if not found:
            local_symbols.append({
                "symbol": active["symbol"],
                "status": "ingesting",
                "timeframe": "MTF"
            })
            
    return {"active_pairs": local_symbols}


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    Permet de suivre le statut et la progression d'une tâche de calcul ou d'ingestion.
    """
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="ID de tâche introuvable.")
    return tasks_db[task_id]


@app.post("/api/indicator/calculate")
async def calculate_indicator_api(req: IndicatorCalculateRequest):
    """
    Exécute de manière optimisée le calcul d'indicateurs via vectorbtpro.
    """
    data = load_numpy_via_zmq(req.exchange, req.symbol, req.timeframe, req.start_time, req.end_time)
    if len(data) == 0:
        raise HTTPException(status_code=404, detail="Données insuffisantes.")
        
    inputs = {
        'open': data['open'],
        'high': data['high'],
        'low': data['low'],
        'close': data['close'],
        'volume': data['volume']
    }
    
    try:
        res = DynamicIndicatorFactory.run_indicator(req.func_name, inputs, req.params)
        outputs_serializable = {}
        for out_name, out_arr in res["outputs"].items():
            outputs_serializable[out_name] = out_arr.tolist()
            
        return {"outputs": outputs_serializable}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calcul de l'indicateur a échoué : {str(e)}")


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


@app.websocket("/api/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_log_handler.connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_log_handler.connections.remove(websocket)
    except Exception:
        if websocket in ws_log_handler.connections:
            ws_log_handler.connections.remove(websocket)


if __name__ == "__main__":
    uvicorn.run("backend.api.gateway:app", host="0.0.0.0", port=8000, reload=True)