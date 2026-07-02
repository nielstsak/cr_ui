import asyncio
import logging
import os
import time
from typing import Dict, Optional, Set, Tuple

import aiohttp
import h5py
import numpy as np

# Local imports
from backend.data.binance_client import BinanceClient
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE

# Setup logger
logger = logging.getLogger("BinanceWebSocketListener")


class BinanceWebSocketListener:
    """
    Asynchronous WebSocket listener for Binance Kline/Candlestick streams.
    Manages dynamic stream subscriptions, in-memory volatile cache for building candles,
    atomic HDF5 disk writes upon candle closure, and a logical watchdog that triggers
    REST gap-fills upon inactivity detection.
    """
    
    def __init__(self, binance_client: Optional[BinanceClient] = None, storage_dir: str = "data"):
        """
        Initializes the WebSocket listener.
        
        Args:
            binance_client: An initialized BinanceClient instance used for REST reconciliation.
            storage_dir: Root directory path for disk storage.
        """
        self.binance_client = binance_client
        self.storage_dir = storage_dir
        
        self._cache: Dict[Tuple[str, str], np.ndarray] = {}  # (SYMBOL, timeframe) -> structured 1-row array
        self._storages: Dict[Tuple[str, str], HDF5Storage] = {}  # (SYMBOL, timeframe) -> HDF5Storage instance
        self._subscriptions: Set[str] = set()  # Set of active stream names (e.g. "btcusdt@kline_1m")
        
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False
        self._last_msg_time = time.time()
        
        self._listener_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None

    def get_storage(self, symbol: str, timeframe: str) -> HDF5Storage:
        """
        Retrieves or initializes a cached HDF5Storage writer instance for the given stream.
        """
        key = (symbol.upper(), timeframe.lower())
        if key not in self._storages:
            # Physical disk path: data/exchange/symbol/timeframe/ohlcv.h5
            file_path = os.path.join(
                self.storage_dir,
                "BINANCE",
                symbol.upper(),
                timeframe.lower(),
                "ohlcv.h5"
            )
            self._storages[key] = HDF5Storage(
                file_path=file_path,
                exchange="BINANCE",
                symbol=symbol,
                timeframe=timeframe
            )
        return self._storages[key]

    def get_current_candle(self, symbol: str, timeframe: str) -> Optional[np.ndarray]:
        """
        Fetches the active building candle from the volatile RAM cache (O(1) memory read).
        Returns None if no tick has been received yet for the stream.
        """
        key = (symbol.upper(), timeframe.lower())
        return self._cache.get(key)

    async def subscribe(self, symbol: str, timeframe: str):
        """
        Dynamically subscribes to a symbol-timeframe kline stream.
        Registers the stream and sends a SUBSCRIBE message if the WebSocket is connected.
        """
        stream = f"{symbol.lower()}@kline_{timeframe.lower()}"
        if stream not in self._subscriptions:
            self._subscriptions.add(stream)
            logger.info(f"Subscribed dynamically to stream: {stream}")
            
            # Send message immediately if socket is alive
            if self._ws and not self._ws.closed:
                subscribe_payload = {
                    "method": "SUBSCRIBE",
                    "params": [stream],
                    "id": int(time.time() * 1000)
                }
                await self._ws.send_json(subscribe_payload)

    async def unsubscribe(self, symbol: str, timeframe: str):
        """
        Dynamically unsubscribes from a stream.
        Removes the local subscription and volatile cache, and sends UNSUBSCRIBE payload.
        """
        stream = f"{symbol.lower()}@kline_{timeframe.lower()}"
        if stream in self._subscriptions:
            self._subscriptions.remove(stream)
            logger.info(f"Unsubscribed dynamically from stream: {stream}")
            
            key = (symbol.upper(), timeframe.lower())
            self._cache.pop(key, None)
            
            # Send message immediately if socket is alive
            if self._ws and not self._ws.closed:
                unsubscribe_payload = {
                    "method": "UNSUBSCRIBE",
                    "params": [stream],
                    "id": int(time.time() * 1000)
                }
                await self._ws.send_json(unsubscribe_payload)

    async def start(self):
        """
        Starts the WebSocket listener loop and watchdog monitoring tasks.
        """
        self._running = True
        self._last_msg_time = time.time()
        self._listener_task = asyncio.create_task(self._run_loop())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("BinanceWebSocketListener tasks started.")

    async def stop(self):
        """
        Gracefully stops background tasks and shuts down the active WebSocket connection.
        """
        self._running = False
        
        # Cancel watchdog and connection loops
        if self._watchdog_task:
            self._watchdog_task.cancel()
        if self._listener_task:
            self._listener_task.cancel()
            
        if self._ws and not self._ws.closed:
            await self._ws.close()
            
        logger.info("BinanceWebSocketListener stopped.")

    async def _run_loop(self):
        """
        Asynchronous loop managing WebSocket lifetime, automatic reconnections,
        and message dispatching.
        """
        websocket_url = "wss://stream.binance.com:9443/ws"
        
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(websocket_url) as ws:
                        self._ws = ws
                        logger.info("WebSocket connected to Binance endpoints.")
                        
                        # Re-register active subscriptions on connection setup
                        if self._subscriptions:
                            subscribe_payload = {
                                "method": "SUBSCRIBE",
                                "params": list(self._subscriptions),
                                "id": int(time.time() * 1000)
                            }
                            await ws.send_json(subscribe_payload)
                            logger.info(f"WebSocket subscriptions registered: {self._subscriptions}")
                            
                        # Reset watchdog timer
                        self._last_msg_time = time.time()
                        
                        async for msg in ws:
                            if not self._running:
                                break
                                
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.json()
                                self._last_msg_time = time.time()
                                
                                if data.get("e") == "kline":
                                    await self._handle_kline(data)
                                    
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                logger.warning("Binance WebSocket closed or encountered an error. Reconnecting...")
                                break
                                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Incurred error in WebSocket run loop: {e}")
                
            if self._running:
                # Preventive cooling sleep before attempting reconnection
                await asyncio.sleep(5)

    async def _handle_kline(self, event: dict):
        """
        Processes incoming Binance WebSocket kline events.
        Updates volatile RAM cache for ongoing ticks, and flushes to HDF5 upon closure.
        """
        symbol = event["s"]
        kline = event["k"]
        timeframe = kline["i"]
        is_closed = kline["x"]
        
        # Build 1-row structured NumPy array
        candle = np.empty(1, dtype=OHLCV_DTYPE)
        candle[0]['open_time'] = int(kline['t'])
        candle[0]['open'] = float(kline['o'])
        candle[0]['high'] = float(kline['h'])
        candle[0]['low'] = float(kline['l'])
        candle[0]['close'] = float(kline['c'])
        candle[0]['volume'] = float(kline['v'])
        candle[0]['quote_vol'] = float(kline['q'])
        candle[0]['trades'] = int(kline['n'])
        
        # Update high-performance volatile RAM cache
        key = (symbol.upper(), timeframe.lower())
        self._cache[key] = candle
        
        # If candle is closed, execute atomic write to HDF5 in executor (non-blocking)
        if is_closed:
            logger.info(f"Candle closed for {symbol} {timeframe} at {candle[0]['open_time']}. Flushing to HDF5.")
            try:
                storage = self.get_storage(symbol, timeframe)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, storage.append_chunk, candle)
            except Exception as e:
                logger.error(f"Failed to append closed kline to HDF5 storage: {e}")

    async def _watchdog_loop(self):
        """
        Background loop checking the health of the connection stream.
        Triggers reconnections and REST Gap Fill reconciliations upon 3-minute silence.
        """
        while self._running:
            await asyncio.sleep(10)
            
            # Check inactivity threshold (180 seconds / 3 minutes)
            if self._subscriptions and (time.time() - self._last_msg_time > 180):
                logger.warning("Watchdog detected stream inactivity. Forcing reconnection and gap-fill.")
                
                # Force close active WebSocket connection (auto-reconnect handles setup)
                if self._ws and not self._ws.closed:
                    try:
                        await self._ws.close()
                    except Exception as e:
                        logger.error(f"Error forcing socket close inside watchdog: {e}")
                        
                # Perform historical REST Gap Fill reconciliation
                await self._reconcile_gaps()
                
                # Shift last message time to prevent instant double trigger
                self._last_msg_time = time.time()

    async def _reconcile_gaps(self):
        """
        Scans HDF5 storage for gaps and queries Binance REST endpoints
        to fetch missing candles and insert them.
        """
        if not self.binance_client:
            logger.warning("BinanceClient not provided. Skipping REST gap-fill.")
            return
            
        for key in list(self._cache.keys()):
            symbol, timeframe = key
            try:
                storage = self.get_storage(symbol, timeframe)
                
                # Fetch last timestamp in HDF5 file
                last_time = -1
                if os.path.exists(storage.file_path):
                    with h5py.File(storage.file_path, 'r', libver='latest', swmr=True) as f:
                        if storage.dataset_path in f:
                            dataset = f[storage.dataset_path]
                            if dataset.shape[0] > 0:
                                last_time = dataset[-1]['open_time']
                                
                if last_time == -1:
                    logger.info(f"No previous data found for {symbol} {timeframe}. Skipping reconciliation.")
                    continue
                    
                now_ms = int(time.time() * 1000)
                logger.info(f"Gap-fill: Checking missing candles for {symbol} {timeframe} starting from {last_time + 1}...")
                
                # Query historical data from REST client
                missing_data = await self.binance_client.fetch_klines_historical(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=last_time + 1,
                    end_time=now_ms
                )
                
                if len(missing_data) > 0:
                    logger.info(f"Gap-fill: Recovered {len(missing_data)} missing candles for {symbol} {timeframe}.")
                    # Write recovered data to HDF5
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, storage.append_chunk, missing_data)
                else:
                    logger.info(f"Gap-fill: No missing candles found for {symbol} {timeframe}.")
                    
            except Exception as e:
                logger.error(f"Error during gap-fill reconciliation for {symbol} {timeframe}: {e}")
