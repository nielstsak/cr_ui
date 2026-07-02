import inspect
import itertools
import logging
from collections import OrderedDict
import numpy as np
import pandas as pd
import talib
import talib.abstract as ta
import vectorbtpro as vbt

# Setup logger
logger = logging.getLogger("DynamicIndicators")


# LRU Cache implementation for storing indicator calculation results
class LRUCache:
    """
    A simple thread-safe in-memory Least Recently Used (LRU) Cache
    using collections.OrderedDict.
    """
    def __init__(self, maxsize: int = 128):
        self.cache = OrderedDict()
        self.maxsize = maxsize

    def get(self, key):
        if key not in self.cache:
            return None
        # Move key to the end to denote recent use
        self.cache.move_to_end(key)
        return self.cache[key]

    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)  # Evict oldest entry


# Module-level static cache registries
_indicator_classes = {}
_lru_cache = LRUCache(maxsize=128)

# Standard synonyms for resolving OHLCV column mappings
SYNONYMS = {
    'close': ['close', 'price', 'close_price'],
    'price': ['close', 'price', 'close_price'],
    'high': ['high', 'high_price'],
    'low': ['low', 'low_price'],
    'open': ['open', 'open_price'],
    'volume': ['volume', 'vol']
}

# Crypto-optimized sensible defaults for the exhaustive indicator list
CUSTOM_DEFAULTS = {
    "SMA": {"timeperiod": 20},
    "EMA": {"timeperiod": 20},
    "DEMA": {"timeperiod": 20},
    "KAMA": {"timeperiod": 20},
    "T3": {"timeperiod": 20},
    "TEMA": {"timeperiod": 20},
    "TRIMA": {"timeperiod": 20},
    "WMA": {"timeperiod": 20},
    "LINEARREG": {"timeperiod": 20},
    "TSF": {"timeperiod": 20},
    "MA": {"timeperiod": 20, "matype": 0},
    "BBANDS": {"timeperiod": 20, "nbdevup": 2.0, "nbdevdn": 2.0},
    "MACD": {"fastperiod": 12, "slowperiod": 26, "signalperiod": 9},
    "MACDEXT": {"fastperiod": 12, "fastmatype": 0, "slowperiod": 26, "slowmatype": 0, "signalperiod": 9, "signalmatype": 0},
    "MACDFIX": {"signalperiod": 9},
    "RSI": {"timeperiod": 14},
    "CCI": {"timeperiod": 14},
    "CMO": {"timeperiod": 14},
    "MOM": {"timeperiod": 14},
    "ROC": {"timeperiod": 14},
    "ROCP": {"timeperiod": 14},
    "ROCR": {"timeperiod": 14},
    "ROCR100": {"timeperiod": 14},
    "WILLR": {"timeperiod": 14},
    "MFI": {"timeperiod": 14},
    "ADX": {"timeperiod": 14},
    "ADXR": {"timeperiod": 14},
    "DX": {"timeperiod": 14},
    "MINUS_DI": {"timeperiod": 14},
    "MINUS_DM": {"timeperiod": 14},
    "PLUS_DI": {"timeperiod": 14},
    "PLUS_DM": {"timeperiod": 14},
    "ATR": {"timeperiod": 14},
    "NATR": {"timeperiod": 14},
    "STOCH": {"fastk_period": 5, "slowk_period": 3, "slowk_matype": 0, "slowd_period": 3, "slowd_matype": 0},
    "STOCHF": {"fastk_period": 5, "fastd_period": 3, "fastd_matype": 0},
    "STOCHRSI": {"timeperiod": 14, "fastk_period": 5, "fastd_period": 3, "fastd_matype": 0},
    "MAX": {"timeperiod": 30},
    "MIN": {"timeperiod": 30},
    "MAXINDEX": {"timeperiod": 30},
    "MININDEX": {"timeperiod": 30},
    "MINMAX": {"timeperiod": 30},
    "MINMAXINDEX": {"timeperiod": 30},
    "SUM": {"timeperiod": 30},
    "VAR": {"timeperiod": 30},
    "STDDEV": {"timeperiod": 30},
    "BETA": {"timeperiod": 30},
    "CORREL": {"timeperiod": 30},
    "AROON": {"timeperiod": 14},
    "AROONOSC": {"timeperiod": 14},
    "ULTOSC": {"timeperiod1": 7, "timeperiod2": 14, "timeperiod3": 28}
}


def make_array_fingerprint(arr: np.ndarray) -> tuple:
    """
    Computes a hashable O(1) fingerprint of a NumPy array based on its shape,
    dtype, and a small selection of boundaries to prevent hashing large byte buffers.
    """
    n = len(arr)
    if n == 0:
        return (arr.dtype, arr.shape, 0)
    sample_indices = np.linspace(0, n - 1, min(5, n)).astype(np.int64)
    samples = tuple(arr[idx] for idx in sample_indices)
    return (arr.dtype, arr.shape, samples)


def make_params_hashable(p: dict) -> tuple:
    """
    Converts indicator parameter dictionaries (which might contain mutable lists
    or numpy arrays) into hashable structures.
    """
    hashable = []
    for k in sorted(p.keys()):
        v = p[k]
        if isinstance(v, (list, tuple)):
            hashable.append((k, tuple(v)))
        elif isinstance(v, np.ndarray):
            hashable.append((k, tuple(v.tolist())))
        else:
            hashable.append((k, v))
    return tuple(hashable)


def make_cache_key(func_name: str, inputs: dict, params: dict, downcast_float32: bool) -> tuple:
    """
    Generates a unique hashable signature key for caching query results.
    """
    inputs_fingerprint = tuple((k, make_array_fingerprint(v)) for k, v in sorted(inputs.items()))
    params_fingerprint = make_params_hashable(params)
    return (func_name, inputs_fingerprint, params_fingerprint, downcast_float32)


def get_talib_metadata(func_name: str) -> dict:
    """
    Introspects dynamic metadata for any TA-Lib indicator and applies custom overrides.
    
    Args:
        func_name: Name of the TA-Lib function (e.g. 'SMA', 'MACD').
        
    Returns:
        A dict containing the group name, required input columns,
        parameters with defaults, and output column names.
    """
    try:
        func = ta.Function(func_name)
    except Exception as e:
        raise ValueError(
            f"Indicator '{func_name}' is not recognized in TA-Lib. "
            f"Ensure function name is valid (uppercase). Error: {str(e)}"
        )
        
    info = func.info
    parameters = dict(info.get("parameters", {}))
    
    if func_name in CUSTOM_DEFAULTS:
        for k, v in CUSTOM_DEFAULTS[func_name].items():
            if k in parameters:
                parameters[k] = v
                
    return {
        "name": info.get("name", func_name),
        "group": info.get("group", ""),
        "inputs": dict(info.get("input_names", {})),
        "parameters": parameters,
        "outputs": list(info.get("output_names", []))
    }


def get_ui_parameter_schema(func_name: str) -> dict:
    """
    Translates TA-Lib parameter schema constraints into a standardized JSON Schema.
    Enriches parameters with sensible UI ranges and moving average enum mappings.
    """
    meta = get_talib_metadata(func_name)
    properties = {}
    
    for param_name, default_val in meta["parameters"].items():
        param_schema = {}
        
        if isinstance(default_val, int):
            param_schema["type"] = "integer"
        elif isinstance(default_val, float):
            param_schema["type"] = "number"
        elif isinstance(default_val, bool):
            param_schema["type"] = "boolean"
        else:
            param_schema["type"] = "string"
            
        param_schema["default"] = default_val
        
        if "matype" in param_name.lower():
            param_schema["type"] = "integer"
            param_schema["enum"] = [0, 1, 2, 3, 4, 5, 6, 7, 8]
            param_schema["description"] = (
                "Moving Average Type: 0=SMA, 1=EMA, 2=WMA, 3=DEMA, "
                "4=TEMA, 5=TRIMA, 6=KAMA, 7=MAMA, 8=T3"
            )
        elif "period" in param_name.lower():
            param_schema["minimum"] = 2
            param_schema["description"] = f"Time window period (minimum: 2, default: {default_val})"
            
        if param_name in ("nbdevup", "nbdevdn"):
            param_schema["minimum"] = 0.1
            param_schema["description"] = f"Standard deviation multiplier (minimum: 0.1, default: {default_val})"
            
        properties[param_name] = param_schema
        
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"Parameter configuration schema for {func_name}",
        "type": "object",
        "properties": properties,
        "required": list(properties.keys())
    }


def resolve_inputs(IndicatorClass, inputs: dict) -> dict:
    """
    Inspects Vectorbt Pro indicator signature arguments and maps
    user-provided OHLCV inputs using standard synonyms.
    """
    sig = inspect.signature(IndicatorClass.run)
    run_args = {}
    
    for param_name, param in sig.parameters.items():
        if param_name in ('close', 'high', 'low', 'open', 'volume', 'real', 'price'):
            candidates = SYNONYMS.get(param_name, [param_name])
            target_key = None
            for c in candidates:
                if c in inputs:
                    target_key = c
                    break
            if target_key:
                run_args[param_name] = inputs[target_key]
            elif param.default == inspect.Parameter.empty:
                raise ValueError(
                    f"Required input argument '{param_name}' could not be resolved from inputs. "
                    f"Available input keys: {list(inputs.keys())}"
                )
    return run_args


class DynamicIndicatorFactory:
    """
    Dynamic indicator computation manager.
    Exposes a unified run_indicator method wrapper implementing vectorbt parameter grid
    generation, memory chunking safety thresholds, downcasting, and LRU caching.
    """
    
    @staticmethod
    def run_indicator(
        func_name: str,
        inputs: dict,
        params: dict,
        downcast_float32: bool = False,
        max_param_combinations: int = 50000
    ) -> dict:
        """
        Executes any TA-Lib indicator dynamically on numpy arrays using Vectorbt Pro.
        
        Args:
            func_name: Name of the TA-Lib indicator (e.g. 'RSI', 'BBANDS').
            inputs: Dictionary containing input numpy arrays (e.g., {'close': close_array}).
            params: Dictionary containing parameter overrides under lists or scalar values.
            downcast_float32: Converts final output values to float32 to reduce memory footprint.
            max_param_combinations: Chunk size threshold to prevent RAM MemoryErrors.
            
        Returns:
            A dictionary containing output arrays and column parameter maps:
            {
                "outputs": {
                    "output_name": np.ndarray (shape: (n_rows, n_combinations)),
                    ...
                },
                "columns": [
                    {"param_name": value, ...},
                    ...
                ]
            }
        """
        cache_key = make_cache_key(func_name, inputs, params, downcast_float32)
        cached_result = _lru_cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Indicator '{func_name}' hit in LRU cache.")
            return cached_result
            
        if func_name not in _indicator_classes:
            _indicator_classes[func_name] = vbt.IndicatorFactory.from_talib(func_name)
        IndicatorClass = _indicator_classes[func_name]
        
        run_inputs = resolve_inputs(IndicatorClass, inputs)
        
        meta = get_talib_metadata(func_name)
        grid_params = {}
        for p_name, default_val in meta["parameters"].items():
            if p_name in params:
                val = params[p_name]
                if isinstance(val, (list, np.ndarray, tuple)):
                    grid_params[p_name] = list(val)
                else:
                    grid_params[p_name] = [val]
            else:
                grid_params[p_name] = [default_val]
                
        param_names = list(grid_params.keys())
        param_values = list(grid_params.values())
        combinations = list(itertools.product(*param_values))
        n_combinations = len(combinations)
        
        logger.info(
            f"Computing {n_combinations} parameter combinations for indicator '{func_name}' "
            f"(Chunking threshold: {max_param_combinations})."
        )
        
        chunks = [
            combinations[idx:idx + max_param_combinations]
            for idx in range(0, n_combinations, max_param_combinations)
        ]
        
        outputs_list = {out_name: [] for out_name in meta["outputs"]}
        final_columns = None
        
        for chunk in chunks:
            chunk_params = {}
            for idx, p_name in enumerate(param_names):
                chunk_params[p_name] = [c[idx] for c in chunk]
                
            res = IndicatorClass.run(**run_inputs, **chunk_params, param_product=False)
            
            for out_name in meta["outputs"]:
                val_df = pd.DataFrame(getattr(res, out_name))
                outputs_list[out_name].append(val_df)
                
        concat_outputs = {}
        df_columns = None
        for out_name in meta["outputs"]:
            df_concat = pd.concat(outputs_list[out_name], axis=1)
            
            if df_columns is None:
                df_columns = df_concat.columns
                
            val_array = df_concat.values
            if downcast_float32:
                val_array = val_array.astype(np.float32)
            concat_outputs[out_name] = val_array
            
        list_of_param_dicts = []
        if df_columns is not None:
            if isinstance(df_columns, pd.MultiIndex):
                names = df_columns.names
                prefix = f"{func_name.lower()}_"
                clean_names = [
                    n[len(prefix):] if n and n.startswith(prefix) else n
                    for n in names
                ]
                for col_tuple in df_columns:
                    list_of_param_dicts.append({
                        clean_names[idx]: col_tuple[idx]
                        for idx in range(len(clean_names))
                    })
            else:
                name = df_columns.name
                prefix = f"{func_name.lower()}_"
                clean_name = name[len(prefix):] if name and name.startswith(prefix) else name
                for col_val in df_columns:
                    list_of_param_dicts.append({clean_name: col_val})
                    
        result = {
            "outputs": concat_outputs,
            "columns": list_of_param_dicts
        }
        
        _lru_cache.set(cache_key, result)
        return result