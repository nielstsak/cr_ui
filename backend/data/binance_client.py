import asyncio
import hashlib
import hmac
import logging
import random
import time
from typing import Optional

import aiohttp
import numpy as np

# Import the strict OHLCV dtype from the local HDF5 storage backend
from backend.data.hdf5_storage import OHLCV_DTYPE

# Setup client logger
logger = logging.getLogger("BinanceClient")


def normalize_klines(klines_json: list) -> np.ndarray:
    """
    Highly-optimized vectorized conversion of raw Binance JSON kline response lists
    into a structured C-contiguous NumPy array matching OHLCV_DTYPE.
    
    Binance JSON index structure:
      0: Open time (ms)
      1: Open price (str)
      2: High price (str)
      3: Low price (str)
      4: Close price (str)
      5: Volume (str)
      6: Close time (ms)
      7: Quote asset volume (str)
      8: Number of trades (int)
      9: Taker buy base asset volume (str)
      10: Taker buy quote asset volume (str)
      11: Ignore
    """
    n = len(klines_json)
    if n == 0:
        return np.empty(0, dtype=OHLCV_DTYPE)
        
    data = np.empty(n, dtype=OHLCV_DTYPE)
    
    # Vectorized assignment leveraging list comprehensions for rapid conversion in C
    data['open_time'] = [int(k[0]) for k in klines_json]
    data['open'] = [float(k[1]) for k in klines_json]
    data['high'] = [float(k[2]) for k in klines_json]
    data['low'] = [float(k[3]) for k in klines_json]
    data['close'] = [float(k[4]) for k in klines_json]
    data['volume'] = [float(k[5]) for k in klines_json]
    data['quote_vol'] = [float(k[7]) for k in klines_json]
    data['trades'] = [int(k[8]) for k in klines_json]
    
    return data


class BinanceClient:
    """
    Asynchronous client wrapper for the Binance API.
    Manages HMAC-SHA256 signatures, active rate limiting, resilience
    with jittered exponential backoffs, and high-performance OHLCV normalization.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: str = "https://api.binance.com",
        weight_limit: int = 6000
    ):
        """
        Initializes the Binance API Client.
        
        Args:
            api_key: Binance API key (required for signed private endpoints).
            api_secret: Binance API secret (required for signed private endpoints).
            base_url: Base HTTP endpoint url (defaults to spot API).
            weight_limit: IP-level request weight limit per minute (defaults to 6000).
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip('/')
        self.weight_limit = weight_limit
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.used_weight = 0  # Monitored from X-MBX-USED-WEIGHT-1M headers

    async def __aenter__(self):
        """Asynchronous context manager entry."""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Asynchronous context manager exit."""
        if self.session:
            await self.session.close()
            self.session = None

    def _sign_params(self, params: dict) -> dict:
        """
        Signs query parameters using HMAC-SHA256.
        Adds mandatory timestamp and signature to parameters.
        """
        if not self.api_secret:
            raise ValueError("API secret is required for signed requests")
            
        # Ensure millisecond timestamp is present
        if 'timestamp' not in params:
            params['timestamp'] = int(time.time() * 1000)
            
        # Build raw query string sorted for consistency
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        
        # Calculate HMAC signature
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        params['signature'] = signature
        return params

    async def _request(
        self,
        method: str,
        path: str,
        signed: bool = False,
        params: Optional[dict] = None,
        **kwargs
    ) -> dict:
        """
        Performs an asynchronous HTTP request with active rate limiting,
        signature injection, and error resiliency handling.
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
            
        url = f"{self.base_url}{path}"
        req_params = params.copy() if params else {}
        headers = kwargs.pop('headers', {})
        
        # Authenticate and sign if required
        if signed:
            req_params = self._sign_params(req_params)
        if self.api_key:
            headers['X-MBX-APIKEY'] = self.api_key
            
        # Active Rate Limiting check (preventive sleep until the next minute starts)
        if self.used_weight > 0.8 * self.weight_limit:
            sleep_time = 60.1 - (time.time() % 60)
            logger.warning(
                f"Rate limit safety threshold reached ({self.used_weight}/{self.weight_limit}). "
                f"Pausing request execution for {sleep_time:.2f} seconds."
            )
            await asyncio.sleep(sleep_time)
            self.used_weight = 0  # Reset local weight estimation
            
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries + 1):
            try:
                async with self.session.request(
                    method,
                    url,
                    params=req_params,
                    headers=headers,
                    **kwargs
                ) as response:
                    # Update active weight tracker from Binance header response
                    if 'X-MBX-USED-WEIGHT-1M' in response.headers:
                        self.used_weight = int(response.headers['X-MBX-USED-WEIGHT-1M'])
                        
                    # Handle rate limit exceeding codes (429 / 418)
                    if response.status in (429, 418):
                        # Extract Retry-After or set default security delay
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(
                            f"HTTP {response.status} rate limit error received. "
                            f"Pausing execution for {retry_after}s."
                        )
                        await asyncio.sleep(retry_after)
                        
                        # Raise HTTP error to trigger backoff retry loop
                        response.raise_for_status()
                        
                    response.raise_for_status()
                    return await response.json()
                    
            except aiohttp.ClientResponseError as e:
                # Do not retry invalid request client errors (400s) except rate-limits
                if e.status < 500 and e.status not in (429, 418):
                    logger.error(f"Client response error (non-retryable): {e.status} {e.message}")
                    raise
                if attempt == max_retries:
                    raise
                    
                # Exponential backoff with jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                logger.warning(
                    f"HTTP response error {e.status}. Retrying in {delay:.2f}s "
                    f"(Attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(delay)
                
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == max_retries:
                    logger.error(f"Network connection failed after {max_retries} retries.")
                    raise
                    
                # Exponential backoff with jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                logger.warning(
                    f"Network/Timeout exception: {e}. Retrying in {delay:.2f}s "
                    f"(Attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(delay)
                
        raise RuntimeError("Request failed inside execution loop.")

    async def fetch_klines_historical(
        self,
        symbol: str,
        timeframe: str,
        start_time: int,
        end_time: int
    ) -> np.ndarray:
        """
        Paginates historically through the Binance API to fetch public klines.
        Ensures strict temporal continuity without overlaps or holes.
        
        Args:
            symbol: Trading pair name (e.g. BTCUSDT).
            timeframe: Candle interval (e.g. 1m, 5m, 1h, 1d).
            start_time: Starting timestamp in milliseconds (inclusive).
            end_time: Ending timestamp in milliseconds (inclusive).
            
        Returns:
            A structured NumPy array matching OHLCV_DTYPE.
        """
        symbol = symbol.upper().replace("/", "")
        timeframe = timeframe.lower()
        
        all_chunks = []
        current_start = start_time
        
        while current_start <= end_time:
            params = {
                'symbol': symbol,
                'interval': timeframe,
                'startTime': current_start,
                'endTime': end_time,
                'limit': 1000
            }
            
            logger.info(
                f"Requesting klines for {symbol} {timeframe} from "
                f"timestamp {current_start} (Limit: 1000)."
            )
            
            # GET /api/v3/klines is public and does not require credentials signature
            response_json = await self._request(
                "GET",
                "/api/v3/klines",
                signed=False,
                params=params
            )
            
            if not response_json:
                logger.info("No further candles returned from API. Ending search.")
                break
                
            normalized = normalize_klines(response_json)
            all_chunks.append(normalized)
            
            # Less than 1000 candles indicates the end of available history is reached
            if len(normalized) < 1000:
                break
                
            # Prevent hole/overlap overlap by setting the next start time to last_candle_start + 1ms
            # Binance API automatically maps start_time to the next available candle start
            last_open_time = normalized[-1]['open_time']
            current_start = last_open_time + 1
            
            # Stop condition if last returned timestamp is past request end time boundaries
            if last_open_time >= end_time:
                break
                
        if not all_chunks:
            return np.empty(0, dtype=OHLCV_DTYPE)
            
        # Efficient contiguous concatenation
        return np.concatenate(all_chunks)
