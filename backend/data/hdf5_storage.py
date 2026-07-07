import os
import h5py
import numba
import numpy as np
from pathlib import Path
from typing import Union, Optional, Any, cast, Dict, List

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
def validate_ohlcv_chunk(
    open_time: np.ndarray, open_p: np.ndarray, high_p: np.ndarray, low_p: np.ndarray,
    close_p: np.ndarray, volume: np.ndarray, quote_vol: np.ndarray, trades: np.ndarray,
    start_idx: int, last_open_time: int, err_indices: np.ndarray, err_types: np.ndarray,
    err_values: np.ndarray, err_count: int
) -> int:
    n = len(open_time)
    max_err = len(err_indices)
    
    for i in range(n):
        if err_count >= max_err: break
            
        if i == 0:
            if last_open_time > 0 and open_time[i] <= last_open_time:
                err_indices[err_count] = start_idx + i
                err_types[err_count] = 0
                err_values[err_count] = float(open_time[i])
                err_count += 1
        else:
            if open_time[i] <= open_time[i-1]:
                err_indices[err_count] = start_idx + i
                err_types[err_count] = 0
                err_values[err_count] = float(open_time[i])
                err_count += 1
        
        if err_count >= max_err: break
                
        if np.isnan(open_p[i]) or np.isinf(open_p[i]) or open_p[i] <= 0:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 1; err_values[err_count] = float(open_p[i]); err_count += 1
        if np.isnan(high_p[i]) or np.isinf(high_p[i]) or high_p[i] <= 0:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 2; err_values[err_count] = float(high_p[i]); err_count += 1
        if np.isnan(low_p[i]) or np.isinf(low_p[i]) or low_p[i] <= 0:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 3; err_values[err_count] = float(low_p[i]); err_count += 1
        if np.isnan(close_p[i]) or np.isinf(close_p[i]) or close_p[i] <= 0:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 4; err_values[err_count] = float(close_p[i]); err_count += 1
        if high_p[i] < open_p[i] or high_p[i] < close_p[i] or high_p[i] < low_p[i] or low_p[i] > open_p[i] or low_p[i] > close_p[i]:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 5; err_values[err_count] = float(high_p[i]); err_count += 1
        if np.isnan(volume[i]) or np.isinf(volume[i]) or volume[i] < 0:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 6; err_values[err_count] = float(volume[i]); err_count += 1
        if np.isnan(quote_vol[i]) or np.isinf(quote_vol[i]) or quote_vol[i] < 0:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 7; err_values[err_count] = float(quote_vol[i]); err_count += 1
        if trades[i] < 0:
            err_indices[err_count] = start_idx + i; err_types[err_count] = 8; err_values[err_count] = float(trades[i]); err_count += 1
            
    return err_count

def scan_full_dataset(filepath: str, dataset_path: str, max_errors: int = 100) -> Dict[str, Any]:
    if not os.path.exists(filepath): return {"status": "FILE_NOT_FOUND", "errors": []}
    with h5py.File(filepath, 'r') as f:
        if dataset_path not in f: return {"status": "DATASET_NOT_FOUND", "errors": []}
        dataset = f[dataset_path]
        total_rows = len(dataset)
        chunk_size = 100_000
        err_indices = np.zeros(max_errors, dtype=np.int64)
        err_types = np.zeros(max_errors, dtype=np.int32)
        err_values = np.zeros(max_errors, dtype=np.float64)
        err_count = 0
        last_open_time = -1
        
        for start_idx in range(0, total_rows, chunk_size):
            end_idx = min(start_idx + chunk_size, total_rows)
            data = dataset[start_idx:end_idx]
            err_count = validate_ohlcv_chunk(
                data['open_time'], data['open'], data['high'], data['low'], data['close'],
                data['volume'], data['quote_vol'], data['trades'], start_idx, last_open_time,
                err_indices, err_types, err_values, err_count
            )
            if len(data) > 0: last_open_time = data['open_time'][-1]
            if err_count >= max_errors: break
                
        error_labels = {
            0: "Non-monotonic timestamp", 1: "Invalid open price (<=0, NaN, or Inf)", 2: "Invalid high price (<=0, NaN, or Inf)",
            3: "Invalid low price (<=0, NaN, or Inf)", 4: "Invalid close price (<=0, NaN, or Inf)",
            5: "Geometric inconsistency", 6: "Invalid volume", 7: "Invalid quote_vol", 8: "Invalid trades"
        }
        
        has_errors = err_count > 0
        reported_errors = [{"row_index": int(err_indices[i]), "error_type": error_labels.get(int(err_types[i]), "Unknown"), "value": float(err_values[i])} for i in range(min(err_count, max_errors))]
            
        return {"status": "CORRUPTED" if has_errors else "OK", "total_rows_scanned": total_rows, "total_errors": err_count, "errors": reported_errors}

class HDF5Storage:
    def __init__(self, file_path: Union[str, Path], exchange: str = "BINANCE", symbol: str = "BTCUSDT", timeframe: str = "1m", mode: str = 'a', libver: str = 'latest', group_path: str = "/OHLCV"):
        self.filepath = Path(file_path)
        self.file_path = str(self.filepath)
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.group_path = group_path
        self.dataset_path = self.group_path.lstrip('/')
        self.mode = mode
        self.libver = libver
        self.file: Optional[h5py.File] = None
        
    def __enter__(self) -> 'HDF5Storage':
        if self.mode in ['w', 'a', 'w-', 'x']:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.file = h5py.File(self.filepath, mode=self.mode, libver=self.libver)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.file is not None:
            self.file.close()

    def enable_swmr(self) -> None:
        if self.file is None: raise RuntimeError("Impossible d'activer SWMR: Fichier non ouvert.")
        if self.mode != 'r': self.file.swmr_mode = True

    def write_array(self, path: str, data: np.ndarray, **kwargs: Any) -> None:
        if self.file is None: raise RuntimeError("Fichier non ouvert.")
        if not isinstance(data, np.ndarray): raise TypeError(f"Le format de données doit être un numpy.ndarray, reçu: {type(data)}")
        if path in self.file: del self.file[path]
        self.file.create_dataset(path, data=data, **kwargs)

    def read_array(self, path: str) -> np.ndarray:
        if self.file is None: raise RuntimeError("Fichier non ouvert.")
        if path not in self.file: raise KeyError(f"Dataset non trouvé au chemin HDF5 interne: {path}")
        return cast(np.ndarray, self.file[path][:])

    def append_chunk(self, chunk: np.ndarray) -> None:
        if not isinstance(chunk, np.ndarray): raise TypeError(f"Le format de données doit être un numpy.ndarray, reçu: {type(chunk)}")
        
        is_ohlcv = self.dataset_path.upper() == "OHLCV"
        if is_ohlcv and chunk.dtype != OHLCV_DTYPE:
            raise ValueError(f"Le chunk doit correspondre au dtype OHLCV: {OHLCV_DTYPE}")
            
        if len(chunk) == 0: return

        is_owner = False
        if self.file is None:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            self.file = h5py.File(self.filepath, mode='a', libver=self.libver)
            is_owner = True

        try:
            path = self.dataset_path
            if path not in self.file:
                self.file.create_dataset(path, data=chunk, maxshape=(None,), chunks=True)
            else:
                dataset = self.file[path]
                
                if is_ohlcv:
                    last_open_time = -1
                    if len(dataset) > 0: last_open_time = dataset[-1]['open_time']
                    err_indices = np.zeros(10, dtype=np.int64)
                    err_types = np.zeros(10, dtype=np.int32)
                    err_values = np.zeros(10, dtype=np.float64)
                    err_count = validate_ohlcv_chunk(
                        chunk['open_time'], chunk['open'], chunk['high'], chunk['low'],
                        chunk['close'], chunk['volume'], chunk['quote_vol'], chunk['trades'],
                        0, last_open_time, err_indices, err_types, err_values, 0
                    )
                    if err_count > 0: raise ValueError(f"OHLCV validation failed: {ERROR_MESSAGES.get(err_types[0] + (1 if err_indices[0]==0 and err_types[0]==0 else 2), 'Unknown')}")

                old_size = dataset.shape[0]
                new_size = old_size + chunk.shape[0]
                dataset.resize((new_size,))
                dataset[old_size:new_size] = chunk
        finally:
            if is_owner:
                self.file.close()
                self.file = None

    def read_chunk(self, start_time: int, end_time: int) -> np.ndarray:
        is_owner = False
        if self.file is None:
            if not self.filepath.exists(): return np.empty(0, dtype=OHLCV_DTYPE if self.dataset_path.upper() == "OHLCV" else object)
            self.file = h5py.File(self.filepath, mode='r', libver=self.libver)
            is_owner = True

        try:
            path = self.dataset_path
            if path not in self.file: return np.empty(0, dtype=OHLCV_DTYPE if path.upper() == "OHLCV" else object)
            dataset = self.file[path]
            if len(dataset) == 0: return np.empty(0, dtype=OHLCV_DTYPE if path.upper() == "OHLCV" else object)

            open_times_arr = dataset['open_time'][:]
            start_idx = np.searchsorted(open_times_arr, start_time, side='left')
            end_idx = np.searchsorted(open_times_arr, end_time, side='left')
            return dataset[start_idx:end_idx]
        finally:
            if is_owner:
                self.file.close()
                self.file = None

    def list_groups(self) -> List[str]:
        groups = []
        if not self.filepath.exists(): return groups
        
        is_owner = False
        if self.file is None:
            self.file = h5py.File(self.filepath, mode='r', libver=self.libver)
            is_owner = True
            
        try:
            if "FEATURES" in self.file:
                features_group = self.file["FEATURES"]
                if isinstance(features_group, h5py.Group):
                    groups = list(features_group.keys())
            return groups
        finally:
            if is_owner:
                self.file.close()
                self.file = None