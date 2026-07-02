import os
import h5py
import numba
import numpy as np

# Strict OHLCV Schema
# - open_time: int64 (timestamp in ms, strictly monotonic increasing)
# - open: float64
# - high: float64
# - low: float64
# - close: float64
# - volume: float64
# - quote_vol: float64
# - trades: int32
OHLCV_DTYPE = np.dtype([
    ('open_time', np.int64),
    ('open', np.float64),
    ('high', np.float64),
    ('low', np.float64),
    ('close', np.float64),
    ('volume', np.float64),
    ('quote_vol', np.float64),
    ('trades', np.int32)
])

# Validation error messages mapping
ERROR_MESSAGES = {
    1: "First timestamp in chunk is not strictly greater than the last timestamp in storage.",
    2: "Timestamps are not strictly monotonically increasing within the chunk.",
    3: "Prices (open, high, low, close) must be strictly positive.",
    4: "High price must be greater than or equal to open, close, and low.",
    5: "Low price must be less than or equal to open, close, and high.",
    6: "Volume, quote_vol, and trades must be non-negative.",
    7: "NaN values are not allowed.",
    8: "Inf values are not allowed."
}

@numba.njit(nogil=True, parallel=False)
def validate_ohlcv_jit(open_time, open_prices, high, low, close, volume, quote_vol, trades, last_open_time):
    """
    Ultra-fast compilation-guaranteed validation function for incoming OHLCV chunks.
    Returns an error code (int) if validation fails, 0 otherwise.
    """
    n = len(open_time)
    if n == 0:
        return 0
        
    # Check strict monotonicity across chunks
    if last_open_time != -1 and open_time[0] <= last_open_time:
        return 1
        
    for i in range(n):
        # Check strict monotonicity within chunk
        if i > 0 and open_time[i] <= open_time[i-1]:
            return 2
            
        # Prices must be strictly positive (> 0)
        if open_prices[i] <= 0 or high[i] <= 0 or low[i] <= 0 or close[i] <= 0:
            return 3
            
        # Geometric consistency rules
        if high[i] < open_prices[i] or high[i] < close[i] or high[i] < low[i]:
            return 4
        if low[i] > open_prices[i] or low[i] > close[i]:
            return 5
            
        # Volume & trades must be non-negative (0.0 volume allowed)
        if volume[i] < 0 or quote_vol[i] < 0 or trades[i] < 0:
            return 6
            
        # Reject NaN values
        if (np.isnan(open_prices[i]) or np.isnan(high[i]) or np.isnan(low[i]) or np.isnan(close[i]) or 
            np.isnan(volume[i]) or np.isnan(quote_vol[i])):
            return 7
            
        # Reject Inf values
        if (np.isinf(open_prices[i]) or np.isinf(high[i]) or np.isinf(low[i]) or np.isinf(close[i]) or 
            np.isinf(volume[i]) or np.isinf(quote_vol[i])):
            return 8
            
    return 0

@numba.njit(nogil=True, parallel=False)
def scan_block_jit(open_time, open_p, high_p, low_p, close_p, volume_p, quote_vol_p, trades_p, start_idx, last_open_time, err_indices, err_types, err_values, err_count):
    """
    Scans a block of OHLCV data for anomalies, updating pre-allocated error structures.
    Uses zero-allocation loops for maximum JIT speed.
    """
    n = len(open_time)
    curr_last_time = last_open_time
    max_err = len(err_indices)
    
    for i in range(n):
        idx = start_idx + i
        t = open_time[i]
        
        # 1. Monotonicity check
        if curr_last_time != -1 and t <= curr_last_time:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 0
                err_values[err_count] = float(t)
            err_count += 1
        curr_last_time = t
        
        # 2. Check open price
        op = open_p[i]
        if np.isnan(op) or np.isinf(op) or op <= 0:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 1
                err_values[err_count] = op
            err_count += 1
            
        # 3. Check high price
        hp = high_p[i]
        if np.isnan(hp) or np.isinf(hp) or hp <= 0:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 2
                err_values[err_count] = hp
            err_count += 1
            
        # 4. Check low price
        lp = low_p[i]
        if np.isnan(lp) or np.isinf(lp) or lp <= 0:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 3
                err_values[err_count] = lp
            err_count += 1
            
        # 5. Check close price
        cp = close_p[i]
        if np.isnan(cp) or np.isinf(cp) or cp <= 0:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 4
                err_values[err_count] = cp
            err_count += 1
            
        # 6. Geometric consistency check
        if not np.isnan(op) and not np.isnan(hp) and not np.isnan(lp) and not np.isnan(cp):
            if hp < op or hp < cp or hp < lp or lp > op or lp > cp:
                if err_count < max_err:
                    err_indices[err_count] = idx
                    err_types[err_count] = 5
                    err_values[err_count] = 0.0
                err_count += 1
                
        # 7. Check volume
        vp = volume_p[i]
        if np.isnan(vp) or np.isinf(vp) or vp < 0:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 6
                err_values[err_count] = vp
            err_count += 1
            
        # 8. Check quote_vol
        qv = quote_vol_p[i]
        if np.isnan(qv) or np.isinf(qv) or qv < 0:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 7
                err_values[err_count] = qv
            err_count += 1
            
        # 9. Check trades
        tr = trades_p[i]
        if tr < 0:
            if err_count < max_err:
                err_indices[err_count] = idx
                err_types[err_count] = 8
                err_values[err_count] = float(tr)
            err_count += 1
            
    return err_count, curr_last_time


class HDF5Storage:
    """
    High-performance storage manager for local persistence of OHLCV data using HDF5.
    Optimized for Vectorbt Pro integration, implementing strict schema validation via Numba JIT,
    Single-Writer Multiple-Reader (SWMR) concurrency, and O(1) causal slicing with in-memory temporal indexing.
    """
    
    def __init__(self, file_path: str, exchange: str, symbol: str, timeframe: str):
        """
        Initializes the HDF5 persistence manager.
        Ensures the physical disk directories exist and caches metadata constraints.
        """
        self.file_path = os.path.abspath(file_path)
        self.exchange = exchange.upper()
        self.symbol = symbol.upper().replace("/", "")
        self.timeframe = timeframe.lower()
        
        self.dataset_path = f"/{self.exchange}/{self.symbol}/{self.timeframe}/ohlcv"
        self._open_time_index = None  # Lazy-loaded primary temporal index
        
        # Ensure physical path under data/{exchange}/{symbol}/{timeframe} directory exists
        # Extract directory from the provided file_path
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        
        # Self-initialize file and verify metadata if already exists
        if os.path.exists(self.file_path):
            with h5py.File(self.file_path, 'r', libver='latest', swmr=True) as f:
                if self.dataset_path in f:
                    ds = f[self.dataset_path]
                    self._verify_metadata(ds)

    def _verify_metadata(self, dataset):
        """
        Checks metadata consistency of an existing dataset to prevent data pollution.
        """
        for attr_name, expected_value in [('exchange', self.exchange), 
                                         ('symbol', self.symbol), 
                                         ('timeframe', self.timeframe)]:
            if attr_name in dataset.attrs:
                val = dataset.attrs[attr_name]
                if isinstance(val, bytes):
                    val = val.decode('utf-8')
                if val != expected_value:
                    raise ValueError(
                        f"Metadata mismatch for {attr_name}. File has '{val}', "
                        f"but storage is initialized with '{expected_value}'."
                    )

    def append_chunk(self, data: np.ndarray):
        """
        Appends an OHLCV chunk to the HDF5 storage.
        Performs strict schema and Numba-accelerated content validation before write.
        Synchronizes memory caching and updates disk metadata for concurrent readers.
        """
        if not isinstance(data, np.ndarray):
            raise TypeError("Data must be a numpy ndarray")
            
        # Convert input array if it's a standard 2D array or has matching fields with different alignments
        if data.dtype != OHLCV_DTYPE:
            if data.ndim == 2 and data.shape[1] == 8:
                converted = np.empty(data.shape[0], dtype=OHLCV_DTYPE)
                converted['open_time'] = data[:, 0].astype(np.int64)
                converted['open'] = data[:, 1].astype(np.float64)
                converted['high'] = data[:, 2].astype(np.float64)
                converted['low'] = data[:, 3].astype(np.float64)
                converted['close'] = data[:, 4].astype(np.float64)
                converted['volume'] = data[:, 5].astype(np.float64)
                converted['quote_vol'] = data[:, 6].astype(np.float64)
                converted['trades'] = data[:, 7].astype(np.int32)
                data = converted
            else:
                try:
                    converted = np.empty(data.shape[0], dtype=OHLCV_DTYPE)
                    converted['open_time'] = data['open_time'].astype(np.int64)
                    converted['open'] = data['open'].astype(np.float64)
                    converted['high'] = data['high'].astype(np.float64)
                    converted['low'] = data['low'].astype(np.float64)
                    converted['close'] = data['close'].astype(np.float64)
                    converted['volume'] = data['volume'].astype(np.float64)
                    converted['quote_vol'] = data['quote_vol'].astype(np.float64)
                    converted['trades'] = data['trades'].astype(np.int32)
                    data = converted
                except (ValueError, KeyError) as e:
                    raise ValueError(
                        f"Data must be a structured array with fields: {list(OHLCV_DTYPE.names)} "
                        f"or a 2D array of shape (N, 8). Error: {str(e)}"
                    )
                    
        n_rows = len(data)
        if n_rows == 0:
            return  # Nothing to write
            
        # Make sure physical folder is present
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        
        # Open in read/write mode with latest library version (required for SWMR)
        with h5py.File(self.file_path, 'a', libver='latest') as f:
            if self.dataset_path in f:
                dataset = f[self.dataset_path]
                self._verify_metadata(dataset)
                last_open_time = dataset[-1]['open_time'] if dataset.shape[0] > 0 else -1
            else:
                # Build directory structure and dataset inside HDF5
                # Use chunking to optimize reads/writes and enable resize capability
                chunk_size = max(1000, n_rows)
                dataset = f.create_dataset(
                    self.dataset_path,
                    shape=(0,),
                    maxshape=(None,),
                    dtype=OHLCV_DTYPE,
                    chunks=(chunk_size,)
                )
                dataset.attrs['exchange'] = self.exchange
                dataset.attrs['symbol'] = self.symbol
                dataset.attrs['timeframe'] = self.timeframe
                last_open_time = -1
                
                # Active SWMR mode right after dataset creation
                f.swmr_mode = True
                
            # Perform strict Numba JIT validation
            err_code = validate_ohlcv_jit(
                data['open_time'],
                data['open'],
                data['high'],
                data['low'],
                data['close'],
                data['volume'],
                data['quote_vol'],
                data['trades'],
                last_open_time
            )
            
            if err_code != 0:
                msg = ERROR_MESSAGES.get(err_code, "Unknown validation error.")
                raise ValueError(f"Validation failed at row append: {msg}")
                
            # Resize dataset to append chunk
            curr_len = dataset.shape[0]
            dataset.resize((curr_len + n_rows,))
            dataset[curr_len:] = data
            dataset.flush()
            
            # Update local memory primary temporal index cache
            if self._open_time_index is None:
                self._open_time_index = data['open_time'].copy()
            else:
                self._open_time_index = np.concatenate((self._open_time_index, data['open_time']))

    def read_chunk(self, start_time: int, end_time: int) -> np.ndarray:
        """
        Reads contiguous slices of data causal-aligned between start_time and end_time (inclusive).
        Leverages internal indexation for O(1) physical search / O(log N) memory search.
        Thread-safe & process-safe using SWMR reader mode.
        """
        if not os.path.exists(self.file_path):
            return np.empty(0, dtype=OHLCV_DTYPE)
            
        with h5py.File(self.file_path, 'r', libver='latest', swmr=True) as f:
            if self.dataset_path not in f:
                return np.empty(0, dtype=OHLCV_DTYPE)
                
            dataset = f[self.dataset_path]
            len_dataset = dataset.shape[0]
            if len_dataset == 0:
                return np.empty(0, dtype=OHLCV_DTYPE)
                
            # Check if local in-memory index is missing or out of sync with concurrent writer processes
            if self._open_time_index is None:
                self._open_time_index = dataset['open_time'][:]
            elif len(self._open_time_index) < len_dataset:
                # Concurrent writer appended data: update index cache causally
                diff_len = len_dataset - len(self._open_time_index)
                missing = dataset['open_time'][-diff_len:]
                self._open_time_index = np.concatenate((self._open_time_index, missing))
            elif len(self._open_time_index) > len_dataset:
                # Dataset truncated or recreated, rebuild cache
                self._open_time_index = dataset['open_time'][:]
                
            # Perform searchsorted binary searches in memory
            start_idx = np.searchsorted(self._open_time_index, start_time, side='left')
            end_idx = np.searchsorted(self._open_time_index, end_time, side='right')
            
            # Boundary checks
            if start_idx >= len(self._open_time_index) or start_idx >= end_idx:
                return np.empty(0, dtype=OHLCV_DTYPE)
                
            # Instantaneous O(1) physical read (slicing)
            return dataset[start_idx:end_idx]

    def scan_integrity(self, max_errors: int = 10000) -> dict:
        """
        Scans the dataset to inspect data integrity (NaN, Inf, negatives, non-monotonic values).
        Processes dataset chunk-by-chunk using compiled JIT loops for performance and O(1) memory overhead.
        """
        if not os.path.exists(self.file_path):
            return {"status": "ERROR", "message": "Storage file does not exist."}
            
        with h5py.File(self.file_path, 'r', libver='latest', swmr=True) as f:
            if self.dataset_path not in f:
                return {"status": "ERROR", "message": "Dataset does not exist in storage."}
                
            dataset = f[self.dataset_path]
            total_rows = dataset.shape[0]
            if total_rows == 0:
                return {"status": "OK", "total_rows_scanned": 0, "total_errors": 0, "errors": []}
                
            # Pre-allocated arrays for JIT logging
            err_indices = np.zeros(max_errors, dtype=np.int64)
            err_types = np.zeros(max_errors, dtype=np.int32)
            err_values = np.zeros(max_errors, dtype=np.float64)
            err_count = 0
            
            # Read and scan by blocks
            block_size = 100000
            last_open_time = -1
            
            for start_idx in range(0, total_rows, block_size):
                end_idx = min(start_idx + block_size, total_rows)
                block_data = dataset[start_idx:end_idx]
                
                err_count, last_open_time = scan_block_jit(
                    block_data['open_time'],
                    block_data['open'],
                    block_data['high'],
                    block_data['low'],
                    block_data['close'],
                    block_data['volume'],
                    block_data['quote_vol'],
                    block_data['trades'],
                    start_idx,
                    last_open_time,
                    err_indices,
                    err_types,
                    err_values,
                    err_count
                )
                
            # Map JIT error codes to messages
            error_labels = {
                0: "Non-monotonic timestamp",
                1: "Invalid open price (<=0, NaN, or Inf)",
                2: "Invalid high price (<=0, NaN, or Inf)",
                3: "Invalid low price (<=0, NaN, or Inf)",
                4: "Invalid close price (<=0, NaN, or Inf)",
                5: "Geometric inconsistency (high < open/close/low, or low > open/close)",
                6: "Invalid volume (<0, NaN, or Inf)",
                7: "Invalid quote_vol (<0, NaN, or Inf)",
                8: "Invalid trades (<0)"
            }
            
            has_errors = err_count > 0
            reported_errors = []
            for i in range(min(err_count, max_errors)):
                reported_errors.append({
                    "row_index": int(err_indices[i]),
                    "error_type": error_labels.get(int(err_types[i]), "Unknown"),
                    "value": float(err_values[i])
                })
                
            return {
                "status": "CORRUPTED" if has_errors else "OK",
                "total_rows_scanned": total_rows,
                "total_errors": err_count,
                "errors": reported_errors
            }
