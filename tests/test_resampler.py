import pytest
import numpy as np
import pandas as pd
import psutil
import os
import time
from backend.core.resampler import resample_ohlcv, timeframe_to_ms
from backend.data.hdf5_storage import OHLCV_DTYPE

def test_timeframe_to_ms():
    """
    Validates conversion of timeframe strings to milliseconds.
    """
    # Pre-defined mappings
    assert timeframe_to_ms('1s') == 1000
    assert timeframe_to_ms('1m') == 60000
    assert timeframe_to_ms('3m') == 180000
    assert timeframe_to_ms('5m') == 300000
    assert timeframe_to_ms('15m') == 900000
    assert timeframe_to_ms('30m') == 1800000
    assert timeframe_to_ms('1h') == 3600000
    assert timeframe_to_ms('2h') == 7200000
    assert timeframe_to_ms('4h') == 14400000
    assert timeframe_to_ms('6h') == 21600000
    assert timeframe_to_ms('8h') == 28800000
    assert timeframe_to_ms('12h') == 43200000
    assert timeframe_to_ms('1d') == 86400000
    assert timeframe_to_ms('1w') == 604800000

    # Custom formats and case sensitivity
    assert timeframe_to_ms('  5M  ') == 300000
    assert timeframe_to_ms('15S') == 15000
    assert timeframe_to_ms('12H') == 43200000
    assert timeframe_to_ms('3d') == 259200000
    assert timeframe_to_ms('2w') == 1209600000

    # Invalid formats
    with pytest.raises(ValueError, match="Unsupported or invalid timeframe format"):
        timeframe_to_ms('abc')
    with pytest.raises(ValueError, match="Unsupported or invalid timeframe format"):
        timeframe_to_ms('5x')
    with pytest.raises(ValueError, match="Unsupported or invalid timeframe format"):
        timeframe_to_ms('')


def test_resample_ohlcv_aggregation():
    """
    Validates correct aggregation of basic 1m candles into a 5m timeframe.
    """
    # Create 10 consecutive 1-minute candles starting at t=60,000 (1 minute)
    # 5m bins will be:
    # Bin 0: [0, 300,000[ -> containing open_times: 60,000, 120,000, 180,000, 240,000
    # Bin 1: [300,000, 600,000[ -> containing open_times: 300,000, 360,000, 420,000, 480,000, 540,000
    # Bin 2: [600,000, 900,000[ -> containing open_times: 600,000
    
    data = np.zeros(10, dtype=OHLCV_DTYPE)
    data['open_time'] = np.array([60000 * i for i in range(1, 11)], dtype=np.int64)
    # open: 10, 11, 12, ...
    data['open'] = np.array([10.0 + i for i in range(10)])
    # high: open + 0.5
    data['high'] = data['open'] + 0.5
    # low: open - 0.5
    data['low'] = data['open'] - 0.5
    # close: open + 0.1
    data['close'] = data['open'] + 0.1
    # volume: 100, 100, ...
    data['volume'] = np.full(10, 100.0)
    # quote_vol: 1000, 1000, ...
    data['quote_vol'] = np.full(10, 1000.0)
    # trades: 10, 10, ...
    data['trades'] = np.full(10, 10, dtype=np.int32)

    # 1m to 5m close alignment
    res = resample_ohlcv(data, '5m', align='close')
    
    # We expect 3 periods because start_t = 0 (for first candle at 60,000)
    # and end_t = 600,000 (for last candle at 600,000)
    assert len(res) == 3
    
    # Check Bin 0: [0, 300000[ (4 candles: 1m, 2m, 3m, 4m)
    # Indexes: 0, 1, 2, 3
    assert res['open_time'][0] == 300000
    assert res['open'][0] == 10.0
    assert res['high'][0] == 13.5  # max high (13.0 + 0.5)
    assert res['low'][0] == 9.5    # min low (10.0 - 0.5)
    assert res['close'][0] == 13.1  # close of last candle in bin (13.0 + 0.1)
    assert res['volume'][0] == 400.0
    assert res['quote_vol'][0] == 4000.0
    assert res['trades'][0] == 40

    # Check Bin 1: [300000, 600000[ (5 candles: 5m, 6m, 7m, 8m, 9m)
    # Indexes: 4, 5, 6, 7, 8
    assert res['open_time'][1] == 600000
    assert res['open'][1] == 14.0
    assert res['high'][1] == 18.5  # max high (18.0 + 0.5)
    assert res['low'][1] == 13.5    # min low (14.0 - 0.5)
    assert res['close'][1] == 18.1  # close of last candle (18.0 + 0.1)
    assert res['volume'][1] == 500.0
    assert res['quote_vol'][1] == 5000.0
    assert res['trades'][1] == 50

    # Check Bin 2: [600000, 900000[ (1 candle: 10m)
    # Index: 9 (open_time = 600,000)
    assert res['open_time'][2] == 900000
    assert res['open'][2] == 19.0
    assert res['high'][2] == 19.5
    assert res['low'][2] == 18.5
    assert res['close'][2] == 19.1
    assert res['volume'][2] == 100.0
    assert res['quote_vol'][2] == 1000.0
    assert res['trades'][2] == 10


def test_resample_ohlcv_gap_handling():
    """
    Validates gap handling (forward-fill of prices, zero-fill of volumes and trades).
    """
    # Create inputs with a gap
    # Source timeframe: 1 minute (60,000 ms)
    # We need first two candles contiguous to avoid timeframe validation issues
    # Inputs:
    # 60,000 (1m)
    # 120,000 (2m)
    # 660,000 (11m) - creates a gap between 300,000 and 600,000
    data = np.zeros(3, dtype=OHLCV_DTYPE)
    data['open_time'] = np.array([60000, 120000, 660000], dtype=np.int64)
    data['open'] = np.array([10.0, 11.0, 15.0])
    data['high'] = np.array([10.5, 11.5, 15.5])
    data['low'] = np.array([9.5, 10.5, 14.5])
    data['close'] = np.array([10.8, 11.2, 15.1])
    data['volume'] = np.array([100.0, 200.0, 500.0])
    data['quote_vol'] = np.array([1000.0, 2000.0, 5000.0])
    data['trades'] = np.array([10, 20, 50], dtype=np.int32)

    res = resample_ohlcv(data, '5m', align='close')
    
    # 5m timeframe bins:
    # Bin 0: [0, 300000[ -> t=60,000, 120,000
    # Bin 1: [300000, 600000[ -> EMPTY (GAP)
    # Bin 2: [600000, 900000[ -> t=660,000
    
    assert len(res) == 3
    
    # Bin 0 (normal)
    assert res['open_time'][0] == 300000
    assert res['open'][0] == 10.0
    assert res['high'][0] == 11.5
    assert res['low'][0] == 9.5
    assert res['close'][0] == 11.2
    assert res['volume'][0] == 300.0
    assert res['quote_vol'][0] == 3000.0
    assert res['trades'][0] == 30

    # Bin 1 (gap): forward-filled with close of Bin 0 (11.2), zero volumes/trades
    assert res['open_time'][1] == 600000
    assert res['open'][1] == 11.2
    assert res['high'][1] == 11.2
    assert res['low'][1] == 11.2
    assert res['close'][1] == 11.2
    assert res['volume'][1] == 0.0
    assert res['quote_vol'][1] == 0.0
    assert res['trades'][1] == 0

    # Bin 2 (normal after gap)
    assert res['open_time'][2] == 900000
    assert res['open'][2] == 15.0
    assert res['high'][2] == 15.5
    assert res['low'][2] == 14.5
    assert res['close'][2] == 15.1
    assert res['volume'][2] == 500.0
    assert res['quote_vol'][2] == 5000.0
    assert res['trades'][2] == 50


def test_resample_ohlcv_alignment():
    """
    Validates open and close temporal alignments.
    """
    data = np.zeros(2, dtype=OHLCV_DTYPE)
    data['open_time'] = np.array([60000, 120000], dtype=np.int64)
    data['open'] = np.array([10.0, 11.0])
    data['high'] = np.array([10.5, 11.5])
    data['low'] = np.array([9.5, 10.5])
    data['close'] = np.array([10.8, 11.2])
    data['volume'] = np.array([100.0, 200.0])
    data['quote_vol'] = np.array([1000.0, 2000.0])
    data['trades'] = np.array([10, 20], dtype=np.int32)

    # 1. Close alignment
    res_close = resample_ohlcv(data, '5m', align='close')
    assert len(res_close) == 1
    assert res_close['open_time'][0] == 300000

    # 2. Open alignment
    res_open = resample_ohlcv(data, '5m', align='open')
    assert len(res_open) == 1
    assert res_open['open_time'][0] == 0


def test_resample_ohlcv_edge_cases():
    """
    Validates extreme/edge cases (empty series, one candle, same timeframe, invalid inputs).
    """
    # 1. Empty input
    empty_data = np.empty(0, dtype=OHLCV_DTYPE)
    res_empty = resample_ohlcv(empty_data, '5m')
    assert len(res_empty) == 0
    assert res_empty.dtype == OHLCV_DTYPE

    # 2. Single candle input
    single_data = np.zeros(1, dtype=OHLCV_DTYPE)
    single_data['open_time'] = np.array([60000], dtype=np.int64)
    single_data['open'] = 10.0
    single_data['high'] = 10.5
    single_data['low'] = 9.5
    single_data['close'] = 10.2
    single_data['volume'] = 100.0
    single_data['quote_vol'] = 1000.0
    single_data['trades'] = 10

    res_single = resample_ohlcv(single_data, '5m', align='close')
    assert len(res_single) == 1
    assert res_single['open_time'][0] == 300000
    assert res_single['open'][0] == 10.0
    assert res_single['high'][0] == 10.5
    assert res_single['low'][0] == 9.5
    assert res_single['close'][0] == 10.2
    assert res_single['volume'][0] == 100.0
    assert res_single['quote_vol'][0] == 1000.0
    assert res_single['trades'][0] == 10

    # 3. Same timeframe resampling (1m to 1m)
    data_same = np.zeros(2, dtype=OHLCV_DTYPE)
    data_same['open_time'] = np.array([60000, 120000], dtype=np.int64)
    data_same['open'] = np.array([10.0, 11.0])
    data_same['high'] = np.array([10.5, 11.5])
    data_same['low'] = np.array([9.5, 10.5])
    data_same['close'] = np.array([10.8, 11.2])
    data_same['volume'] = np.array([100.0, 200.0])
    data_same['quote_vol'] = np.array([1000.0, 2000.0])
    data_same['trades'] = np.array([10, 20], dtype=np.int32)

    res_same = resample_ohlcv(data_same, '1m', align='close')
    assert len(res_same) == 2
    assert res_same['open_time'][0] == 120000
    assert res_same['open_time'][1] == 180000
    assert res_same['open'][0] == 10.0
    assert res_same['close'][1] == 11.2

    # 4. Invalid Inputs - Not a numpy array
    with pytest.raises(TypeError, match="Input data must be a NumPy array"):
        resample_ohlcv([1, 2, 3], '5m')

    # 5. Invalid Inputs - Wrong dtype
    wrong_dtype_data = np.zeros(2, dtype=[('open_time', np.int64), ('close', np.float64)])
    with pytest.raises(ValueError, match="Input array must match strict OHLCV_DTYPE"):
        resample_ohlcv(wrong_dtype_data, '5m')

    # 6. Invalid Inputs - Target timeframe smaller than source data timeframe
    data_1h = np.zeros(2, dtype=OHLCV_DTYPE)
    data_1h['open_time'] = np.array([3600000, 7200000], dtype=np.int64) # 1h and 2h
    with pytest.raises(ValueError, match="is smaller than source data timeframe"):
        resample_ohlcv(data_1h, '5m')


def test_resample_ohlcv_vs_pandas():
    """
    Compares Numba JIT resampler results against Pandas resampling
    to validate numerical accuracy (tolerance < 1e-9).
    """
    n = 200
    np.random.seed(42)
    data = np.zeros(n, dtype=OHLCV_DTYPE)
    data['open_time'] = np.arange(1, n + 1, dtype=np.int64) * 60000
    data['open'] = np.random.uniform(10.0, 100.0, n)
    data['high'] = data['open'] + np.random.uniform(0.1, 1.0, n)
    data['low'] = data['open'] - np.random.uniform(0.1, 1.0, n)
    data['close'] = np.random.uniform(data['low'], data['high'], n)
    data['volume'] = np.random.uniform(10.0, 1000.0, n)
    data['quote_vol'] = data['volume'] * data['close']
    data['trades'] = np.random.randint(1, 100, n)

    # 1. Compare standard aggregation
    res_jit = resample_ohlcv(data, '5m', align='open')

    df = pd.DataFrame(data)
    df.index = pd.to_datetime(df['open_time'], unit='ms')
    df_res = df.resample('5min', closed='left', label='left').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'quote_vol': 'sum',
        'trades': 'sum'
    })
    
    # Handle possible empty rows by forward-filling prices and zero-filling volume/trades
    last_close = df_res['close'].ffill()
    df_res['open'] = df_res['open'].fillna(last_close)
    df_res['high'] = df_res['high'].fillna(last_close)
    df_res['low'] = df_res['low'].fillna(last_close)
    df_res['close'] = df_res['close'].fillna(last_close)
    df_res['volume'] = df_res['volume'].fillna(0.0)
    df_res['quote_vol'] = df_res['quote_vol'].fillna(0.0)
    df_res['trades'] = df_res['trades'].fillna(0).astype(np.int32)
    df_res['open_time'] = df_res.index.astype('int64') // 10**6

    res_pd = np.empty(len(df_res), dtype=OHLCV_DTYPE)
    res_pd['open_time'] = df_res['open_time'].values
    res_pd['open'] = df_res['open'].values
    res_pd['high'] = df_res['high'].values
    res_pd['low'] = df_res['low'].values
    res_pd['close'] = df_res['close'].values
    res_pd['volume'] = df_res['volume'].values
    res_pd['quote_vol'] = df_res['quote_vol'].values
    res_pd['trades'] = df_res['trades'].values

    # Check length
    assert len(res_jit) == len(res_pd)
    # Check timestamps and integer fields exactly
    np.testing.assert_array_equal(res_jit['open_time'], res_pd['open_time'])
    np.testing.assert_array_equal(res_jit['trades'], res_pd['trades'])
    # Validate numerical fields with tolerance < 1e-9
    for field in ['open', 'high', 'low', 'close', 'volume', 'quote_vol']:
        np.testing.assert_allclose(res_jit[field], res_pd[field], rtol=1e-9, atol=1e-9)


def test_resample_ohlcv_memory_leak():
    """
    Profiles RAM memory usage to ensure no leak exists (RAM limit < 8GB).
    """
    process = psutil.Process(os.getpid())
    
    n_candles = 50000
    data = np.zeros(n_candles, dtype=OHLCV_DTYPE)
    data['open_time'] = np.arange(1, n_candles + 1, dtype=np.int64) * 60000
    data['open'] = np.random.uniform(10.0, 100.0, n_candles)
    data['high'] = data['open'] + 1.0
    data['low'] = data['open'] - 1.0
    data['close'] = data['open']
    data['volume'] = np.random.uniform(1.0, 100.0, n_candles)
    data['quote_vol'] = data['volume'] * data['close']
    data['trades'] = np.random.randint(1, 10, n_candles)
    
    # Warm up / compilation
    _ = resample_ohlcv(data, '5m')
    
    mem_before = process.memory_info().rss
    
    # Run resample loop 100 times to simulate high usage
    for _ in range(100):
        _ = resample_ohlcv(data, '15m')
        
    mem_after = process.memory_info().rss
    mem_growth_mb = (mem_after - mem_before) / (1024 * 1024)
    total_rss_mb = mem_after / (1024 * 1024)
    
    # Assert that memory growth is negligible (< 20MB) and total memory is well below 8GB (8192MB)
    assert mem_growth_mb < 20.0
    assert total_rss_mb < 8192.0


def test_resample_ohlcv_performance():
    """
    Profiles CPU execution speed to ensure fast resampling performance.
    """
    n_candles = 100000
    data = np.zeros(n_candles, dtype=OHLCV_DTYPE)
    data['open_time'] = np.arange(1, n_candles + 1, dtype=np.int64) * 60000
    data['open'] = np.random.uniform(10.0, 100.0, n_candles)
    data['high'] = data['open'] + 1.0
    data['low'] = data['open'] - 1.0
    data['close'] = data['open']
    data['volume'] = np.random.uniform(1.0, 100.0, n_candles)
    data['quote_vol'] = data['volume'] * data['close']
    data['trades'] = np.random.randint(1, 10, n_candles)
    
    # Warm up
    _ = resample_ohlcv(data, '5m')
    
    start_time = time.perf_counter()
    _ = resample_ohlcv(data, '15m')
    end_time = time.perf_counter()
    
    elapsed = end_time - start_time
    
    # Assert CPU performance is under 50ms for 100,000 candles
    assert elapsed < 0.050
