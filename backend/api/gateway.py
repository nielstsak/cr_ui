
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from backend.api.runs import router as runs_router, init_database_and_runs, sync_database_with_disk
from backend.api.routes_data import router as data_router

logger = logging.getLogger("GatewayAPI")

class AppStateManager:
    def __init__(self, file_path: str = "app_state.json"):
        self.file_path = os.path.abspath(file_path)
        self.state = {
            "active_pairs": [],
            "configurations": { "initial_balance": 10000.0, "fee_rate": 0.001, "slippage_rate": 0.0005, "mmr": 0.05, "leverage": 1.0, "storage_dir": "data" },
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
            except Exception: pass

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception: pass

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
app.include_router(data_router)

@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_running_loop()
    ws_log_handler.loop = loop
    ws_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logging.getLogger().addHandler(ws_log_handler)
    logging.getLogger().setLevel(logging.INFO)
    
    init_database_and_runs()
    sync_database_with_disk()

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks_db: raise HTTPException(status_code=404, detail="Task introuvable.")
    return tasks_db[task_id]

@app.websocket("/api/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_log_handler.connections.add(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        ws_log_handler.connections.remove(websocket)

from backend.api.routes_ingestion import router as ingestion_router
from backend.api.routes_indicators import router as indicators_router
from backend.api.routes_feature_engineering import router as feature_engineering_router
from backend.api.routes_optuna import router as optuna_router

app.include_router(ingestion_router)
app.include_router(indicators_router)
app.include_router(feature_engineering_router)
app.include_router(optuna_router)

if __name__ == "__main__":
    uvicorn.run("backend.api.gateway:app", host="0.0.0.0", port=8000, reload=True)