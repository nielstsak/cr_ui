import time
import psutil
import os
import numpy as np

from backend.data.hdf5_storage import OHLCV_DTYPE
from backend.core.resampler import resample_ohlcv
from backend.core.indicators import DynamicIndicatorFactory, _lru_cache


def run_resampling_benchmark(n_candles: int = 1000000):
    print(f"\n--- Running CPU Resampling Benchmark ({n_candles:,} candles) ---")
    
    # Generate random test candles
    np.random.seed(42)
    data = np.zeros(n_candles, dtype=OHLCV_DTYPE)
    data['open_time'] = np.arange(1, n_candles + 1, dtype=np.int64) * 60000
    data['open'] = np.random.uniform(10.0, 100.0, n_candles)
    data['high'] = data['open'] + 1.0
    data['low'] = data['open'] - 1.0
    data['close'] = data['open']
    data['volume'] = np.random.uniform(1.0, 100.0, n_candles)
    data['quote_vol'] = data['volume'] * data['close']
    data['trades'] = np.random.randint(1, 10, n_candles)

    # Warm up compilation
    _ = resample_ohlcv(data[:1000], '5m')

    # Benchmark run
    t0 = time.perf_counter()
    resampled = resample_ohlcv(data, '15m')
    t1 = time.perf_counter()
    
    elapsed_ms = (t1 - t0) * 1000
    print(f"Resampling of {n_candles:,} candles to 15m completed.")
    print(f"Output shape: {resampled.shape}")
    print(f"Time elapsed: {elapsed_ms:.2f} ms")
    
    if elapsed_ms < 50.0:
        print("SUCCESS: Resampling completed in less than 50 ms!")
    else:
        print("WARNING: Resampling exceeded the 50 ms threshold.")


def run_cache_benchmark():
    print("\n--- Running Indicators LRU Cache Benchmark ---")
    
    # Clear active cache
    _lru_cache.cache.clear()
    
    np.random.seed(88)
    close = np.random.uniform(50.0, 60.0, 100000)
    inputs = {'close': close}
    params = {'timeperiod': [5, 10, 15]}

    # Cold Run (calculation + compilation)
    t0 = time.perf_counter()
    _ = DynamicIndicatorFactory.run_indicator('SMA', inputs, params)
    t1 = time.perf_counter()
    cold_ms = (t1 - t0) * 1000
    print(f"Cold Run (calculation + caching): {cold_ms:.2f} ms")

    # Warm Run (cache hit)
    t2 = time.perf_counter()
    _ = DynamicIndicatorFactory.run_indicator('SMA', inputs, params)
    t3 = time.perf_counter()
    warm_ms = (t3 - t2) * 1000
    print(f"Warm Run (cache hit retrieval): {warm_ms:.2f} ms")

    # Hit rate calculation
    improvement = cold_ms / max(0.001, warm_ms)
    print(f"Speed Improvement Factor: {improvement:.1f}x")
    
    if improvement >= 5.0:
        print("SUCCESS: Cache hit rate validated. Retrieval is >5x faster!")
    else:
        print("WARNING: Cache hit rate retrieval is less than 5x faster.")


def print_memory_footprint():
    process = psutil.Process(os.getpid())
    rss_mb = process.memory_info().rss / (1024 * 1024)
    print(f"\n--- Current Process RSS Memory Footprint ---")
    print(f"RSS Memory: {rss_mb:.2f} MB")
    
    if rss_mb < 8192.0:
         print("SUCCESS: Memory footprint is well below the 8GB limit!")
    else:
         print("WARNING: Memory footprint exceeds the 8GB limit.")


if __name__ == "__main__":
    run_resampling_benchmark(1000000)
    run_cache_benchmark()
    print_memory_footprint()
