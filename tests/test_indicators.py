import pytest
import numpy as np
import pandas as pd
import time
import talib
from backend.core.indicators import (
    get_talib_metadata,
    get_ui_parameter_schema,
    DynamicIndicatorFactory,
    _lru_cache
)

def test_get_talib_metadata():
    """
    Validates dynamic introspection of TA-Lib indicator signatures.
    """
    # 1. Test RSI
    rsi_meta = get_talib_metadata('RSI')
    assert rsi_meta['name'] == 'RSI'
    assert rsi_meta['group'] == 'Momentum Indicators'
    assert 'price' in rsi_meta['inputs']
    assert rsi_meta['parameters']['timeperiod'] == 14
    assert rsi_meta['outputs'] == ['real']

    # 2. Test BBANDS (multi-input, multi-parameter, multi-output)
    bb_meta = get_talib_metadata('BBANDS')
    assert bb_meta['name'] == 'BBANDS'
    assert bb_meta['group'] == 'Overlap Studies'
    assert 'price' in bb_meta['inputs']
    assert 'timeperiod' in bb_meta['parameters']
    assert 'nbdevup' in bb_meta['parameters']
    assert 'nbdevdn' in bb_meta['parameters']
    assert 'matype' in bb_meta['parameters']
    assert bb_meta['outputs'] == ['upperband', 'middleband', 'lowerband']

    # 3. Invalid indicator name raises ValueError
    with pytest.raises(ValueError, match="is not recognized in TA-Lib"):
        get_talib_metadata('INVALID_INDICATOR_NAME')


def test_get_ui_parameter_schema():
    """
    Validates parameter schema translation to JSON Schema for the UI.
    """
    # 1. Test RSI schema
    rsi_schema = get_ui_parameter_schema('RSI')
    assert rsi_schema['$schema'] == 'http://json-schema.org/draft-07/schema#'
    assert rsi_schema['type'] == 'object'
    assert 'timeperiod' in rsi_schema['properties']
    assert rsi_schema['properties']['timeperiod']['type'] == 'integer'
    assert rsi_schema['properties']['timeperiod']['default'] == 14
    assert rsi_schema['properties']['timeperiod']['minimum'] == 2

    # 2. Test BBANDS schema with matype enum and standard deviations
    bb_schema = get_ui_parameter_schema('BBANDS')
    assert 'matype' in bb_schema['properties']
    assert bb_schema['properties']['matype']['type'] == 'integer'
    assert 'enum' in bb_schema['properties']['matype']
    assert bb_schema['properties']['matype']['enum'] == [0, 1, 2, 3, 4, 5, 6, 7, 8]

    assert 'nbdevup' in bb_schema['properties']
    assert bb_schema['properties']['nbdevup']['type'] == 'number'
    assert bb_schema['properties']['nbdevup']['minimum'] == 0.1

    assert 'nbdevdn' in bb_schema['properties']
    assert bb_schema['properties']['nbdevdn']['type'] == 'number'
    assert bb_schema['properties']['nbdevdn']['minimum'] == 0.1


def test_run_indicator_grid_execution():
    """
    Validates dynamic execution and parameter grids with multi-index matching.
    """
    np.random.seed(42)
    close = np.random.uniform(50.0, 150.0, 100)
    inputs = {'close': close}

    # Execute SMA with a grid of timeperiods
    res = DynamicIndicatorFactory.run_indicator(
        'SMA',
        inputs,
        {'timeperiod': [5, 10, 15]}
    )

    # 3 parameter combinations -> 3 columns
    assert 'real' in res['outputs']
    assert res['outputs']['real'].shape == (100, 3)
    assert len(res['columns']) == 3
    assert res['columns'][0] == {'timeperiod': 5}
    assert res['columns'][1] == {'timeperiod': 10}
    assert res['columns'][2] == {'timeperiod': 15}

    # Execute BBANDS with a multi-parameter grid
    res_bb = DynamicIndicatorFactory.run_indicator(
        'BBANDS',
        inputs,
        {
            'timeperiod': [10, 20],
            'nbdevup': [2.0],
            'nbdevdn': [2.0]
        }
    )
    # 2 periods * 1 nbdevup * 1 nbdevdn = 2 combinations
    assert 'upperband' in res_bb['outputs']
    assert 'middleband' in res_bb['outputs']
    assert 'lowerband' in res_bb['outputs']
    assert res_bb['outputs']['upperband'].shape == (100, 2)
    assert len(res_bb['columns']) == 2
    assert res_bb['columns'][0] == {'timeperiod': 10, 'nbdevup': 2.0, 'nbdevdn': 2.0, 'matype': 0}
    assert res_bb['columns'][1] == {'timeperiod': 20, 'nbdevup': 2.0, 'nbdevdn': 2.0, 'matype': 0}


def test_run_indicator_cross_validation():
    """
    Compares DynamicIndicatorFactory outputs with direct TA-Lib C-API executions
    and asserts numerical equality within a strict absolute tolerance of < 1e-9.
    """
    np.random.seed(123)
    close = np.random.uniform(10.0, 100.0, 200)
    inputs = {'close': close}

    # 1. Cross-validate RSI
    res_rsi = DynamicIndicatorFactory.run_indicator('RSI', inputs, {'timeperiod': 14})
    expected_rsi = talib.RSI(close, timeperiod=14)
    # Compare only non-NaN indices
    nan_mask = np.isnan(expected_rsi)
    assert np.array_equal(np.isnan(res_rsi['outputs']['real'][:, 0]), nan_mask)
    np.testing.assert_allclose(
        res_rsi['outputs']['real'][~nan_mask, 0],
        expected_rsi[~nan_mask],
        rtol=1e-12,
        atol=1e-12
    )

    # 2. Cross-validate BBANDS
    res_bb = DynamicIndicatorFactory.run_indicator(
        'BBANDS',
        inputs,
        {'timeperiod': 20, 'nbdevup': 2.0, 'nbdevdn': 2.0}
    )
    expected_upper, expected_middle, expected_lower = talib.BBANDS(
        close,
        timeperiod=20,
        nbdevup=2.0,
        nbdevdn=2.0,
        matype=0
    )
    
    nan_mask_bb = np.isnan(expected_middle)
    for out_name, expected_arr in [
        ('upperband', expected_upper),
        ('middleband', expected_middle),
        ('lowerband', expected_lower)
    ]:
        np.testing.assert_allclose(
            res_bb['outputs'][out_name][~nan_mask_bb, 0],
            expected_arr[~nan_mask_bb],
            rtol=1e-12,
            atol=1e-12
        )


def test_run_indicator_chunking():
    """
    Validates parameter grid execution chunking behavior.
    """
    np.random.seed(99)
    close = np.random.uniform(10.0, 100.0, 100)
    inputs = {'close': close}
    params = {'timeperiod': [5, 10, 15, 20, 25]}

    # 1. Run without chunking (max size = 100)
    res_no_chunk = DynamicIndicatorFactory.run_indicator(
        'SMA',
        inputs,
        params,
        max_param_combinations=100
    )

    # 2. Run with chunking (max size = 2, so it will split into 3 chunks: [2, 2, 1])
    res_chunk = DynamicIndicatorFactory.run_indicator(
        'SMA',
        inputs,
        params,
        max_param_combinations=2
    )

    # Validate they are identical
    assert len(res_chunk['columns']) == len(res_no_chunk['columns'])
    assert res_chunk['columns'] == res_no_chunk['columns']
    
    # Check data outputs are equal
    np.testing.assert_allclose(
        res_chunk['outputs']['real'],
        res_no_chunk['outputs']['real'],
        equal_nan=True
    )


def test_run_indicator_lru_cache():
    """
    Validates that the LRU cache is working and speeds up execution times.
    """
    # Clear cache
    _lru_cache.cache.clear()
    
    np.random.seed(88)
    close = np.random.uniform(50.0, 60.0, 1000)
    inputs = {'close': close}
    params = {'timeperiod': [5, 10, 15]}

    # Cold Run (compile / run)
    t0 = time.perf_counter()
    res1 = DynamicIndicatorFactory.run_indicator('SMA', inputs, params)
    t1 = time.perf_counter()
    cold_time = t1 - t0

    # Warm Run (cache hit)
    t2 = time.perf_counter()
    res2 = DynamicIndicatorFactory.run_indicator('SMA', inputs, params)
    t3 = time.perf_counter()
    warm_time = t3 - t2

    # Verify identical output objects
    assert res1 is res2
    
    # Assert cache contains the key
    assert len(_lru_cache.cache) == 1

    # Assert warm execution is significantly faster (at least 5 times faster)
    assert warm_time < (cold_time / 5.0)


def test_run_indicator_downcasting():
    """
    Verifies that float32 downcasting operates correctly.
    """
    np.random.seed(77)
    close = np.random.uniform(10.0, 50.0, 100)
    inputs = {'close': close}

    # 1. Without downcasting
    res_double = DynamicIndicatorFactory.run_indicator(
        'RSI',
        inputs,
        {'timeperiod': 14},
        downcast_float32=False
    )
    assert res_double['outputs']['real'].dtype == np.float64

    # 2. With downcasting
    res_float = DynamicIndicatorFactory.run_indicator(
        'RSI',
        inputs,
        {'timeperiod': 14},
        downcast_float32=True
    )
    assert res_float['outputs']['real'].dtype == np.float32

    # Assert value integrity with typical single-precision tolerance
    np.testing.assert_allclose(
        res_float['outputs']['real'],
        res_double['outputs']['real'].astype(np.float32),
        equal_nan=True
    )
