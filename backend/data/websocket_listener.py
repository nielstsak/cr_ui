# FICHIER : backend/data/websocket_listener.py
import asyncio
import logging
import os
import time
from typing import Dict, Optional, Set, Tuple

import aiohttp
import h5py
import numpy as np

from backend.data.binance_client import BinanceClient
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE
from backend.core.indicator_engine import auto_compute_features

logger = logging.getLogger("BinanceWebSocketListener")

class BinanceWebSocketListener:
    def __init__(self, binance_client: Optional[BinanceClient] = None, storage_dir: str = "data"):
        self.binance_client = binance_client
        self.storage_dir = storage_dir
        
        self._cache: Dict[Tuple[str, str], np.ndarray] = {}  
        self._storages: Dict[Tuple[str, str], HDF5Storage] = {}  
        self._subscriptions: Set[str] = set()  
        
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False
        self._last_msg_time = time.time()
        
        self._listener_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None

    def get_storage(self, symbol: str, timeframe: str) -> HDF5Storage:
        key = (symbol.upper(), timeframe.lower())
        if key not in self._storages:
            file_path = os.path.join(self.storage_dir, "BINANCE", symbol.upper(), timeframe.lower(), "ohlcv.h5")
            self._storages[key] = HDF5Storage(file_path=file_path, exchange="BINANCE", symbol=symbol, timeframe=timeframe)
        return self._storages[key]

    def get_current_candle(self, symbol: str, timeframe: str) -> Optional[np.ndarray]:
        key = (symbol.upper(), timeframe.lower())
        return self._cache.get(key)

    async def subscribe(self, symbol: str, timeframe: str):
        stream = f"{symbol.lower()}@kline_{timeframe.lower()}"
        if stream not in self._subscriptions:
            self._subscriptions.add(stream)
            logger.info(f"Subscribed dynamically to stream: {stream}")
            if self._ws and not self._ws.closed:
                subscribe_payload = {"method": "SUBSCRIBE", "params": [stream], "id": int(time.time() * 1000)}
                await self._ws.send_json(subscribe_payload)

    async def unsubscribe(self, symbol: str, timeframe: str):
        stream = f"{symbol.lower()}@kline_{timeframe.lower()}"
        if stream in self._subscriptions:
            self._subscriptions.remove(stream)
            logger.info(f"Unsubscribed dynamically from stream: {stream}")
            key = (symbol.upper(), timeframe.lower())
            self._cache.pop(key, None)
            if self._ws and not self._ws.closed:
                unsubscribe_payload = {"method": "UNSUBSCRIBE", "params": [stream], "id": int(time.time() * 1000)}
                await self._ws.send_json(unsubscribe_payload)

    async def start(self):
        self._running = True
        self._last_msg_time = time.time()
        self._listener_task = asyncio.create_task(self._run_loop())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("BinanceWebSocketListener tasks started.")

    async def stop(self):
        self._running = False
        if self._watchdog_task: self._watchdog_task.cancel()
        if self._listener_task: self._listener_task.cancel()
        if self._ws and not self._ws.closed: await self._ws.close()
        logger.info("BinanceWebSocketListener stopped.")

    async def _run_loop(self):
        websocket_url = "wss://stream.binance.com:9443/ws"
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(websocket_url) as ws:
                        self._ws = ws
                        logger.info("WebSocket connected to Binance endpoints.")
                        if self._subscriptions:
                            subscribe_payload = {"method": "SUBSCRIBE", "params": list(self._subscriptions), "id": int(time.time() * 1000)}
                            await ws.send_json(subscribe_payload)
                        self._last_msg_time = time.time()
                        
                        async for msg in ws:
                            if not self._running: break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.json()
                                self._last_msg_time = time.time()
                                if data.get("e") == "kline": await self._handle_kline(data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR): break
            except asyncio.CancelledError: break
            except Exception as e: logger.error(f"Incurred error in WebSocket run loop: {e}")
            if self._running: await asyncio.sleep(5)

    async def _handle_kline(self, event: dict):
        symbol = event["s"]
        kline = event["k"]
        timeframe = kline["i"]
        is_closed = kline["x"]
        
        candle = np.empty(1, dtype=OHLCV_DTYPE)
        candle[0]['open_time'] = int(kline['t'])
        candle[0]['open'] = float(kline['o'])
        candle[0]['high'] = float(kline['h'])
        candle[0]['low'] = float(kline['l'])
        candle[0]['close'] = float(kline['c'])
        candle[0]['volume'] = float(kline['v'])
        candle[0]['quote_vol'] = float(kline['q'])
        candle[0]['trades'] = int(kline['n'])
        
        key = (symbol.upper(), timeframe.lower())
        self._cache[key] = candle
        
        if is_closed:
            logger.info(f"Candle closed for {symbol} {timeframe}. Flushing to HDF5.")
            try:
                storage = self.get_storage(symbol, timeframe)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, storage.append_chunk, candle)
            except Exception as e:
                logger.error(f"Failed to append closed kline to HDF5 storage: {e}")

    async def _watchdog_loop(self):
        while self._running:
            await asyncio.sleep(10)
            if self._subscriptions and (time.time() - self._last_msg_time > 180):
                logger.warning("Watchdog detected stream inactivity. Forcing reconnection and gap-fill.")
                if self._ws and not self._ws.closed:
                    try: await self._ws.close()
                    except Exception as e: logger.error(f"Error forcing socket close inside watchdog: {e}")
                await self._reconcile_gaps()
                self._last_msg_time = time.time()

    async def _reconcile_gaps(self):
        if not self.binance_client:
            logger.warning("BinanceClient not provided. Skipping REST gap-fill.")
            return
            
        for key in list(self._cache.keys()):
            symbol, timeframe = key
            try:
                storage = self.get_storage(symbol, timeframe)
                last_time = -1
                if os.path.exists(storage.file_path):
                    with h5py.File(storage.file_path, 'r', libver='latest', swmr=True) as f:
                        if storage.dataset_path in f:
                            dataset = f[storage.dataset_path]
                            if dataset.shape[0] > 0: last_time = dataset[-1]['open_time']
                                
                if last_time == -1: continue
                    
                now_ms = int(time.time() * 1000)
                missing_data = await self.binance_client.fetch_klines_historical(symbol=symbol, timeframe=timeframe, start_time=last_time + 1, end_time=now_ms)
                
                if len(missing_data) > 0:
                    logger.info(f"Gap-fill: Recovered {len(missing_data)} candles for {symbol} {timeframe}.")
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, storage.append_chunk, missing_data)
                    
                    # TRIGGER 3: Automatisation post gap-fill
                    await loop.run_in_executor(None, auto_compute_features, self.storage_dir, "BINANCE", symbol, timeframe)
                else:
                    logger.info(f"Gap-fill: No missing candles found for {symbol} {timeframe}.")
            except Exception as e:
                logger.error(f"Error during gap-fill reconciliation for {symbol} {timeframe}: {e}")