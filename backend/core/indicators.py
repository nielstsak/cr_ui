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


def make_array_fingerprint(arr: np.ndarray) -> tuple:
    """
    Computes a hashable O(1) fingerprint of a NumPy array based on its shape,
    dtype, and a small selection of boundaries to prevent hashing large byte buffers.
    """
    n = len(arr)
    if n == 0:
        return (arr.dtype, arr.shape, 0)
    # Sample up to 5 elements (start, end, and middle increments)
    sample_indices = np.linspace(0, n - 1, min(5, n)).astype(np.int64)
    # Convert samples to a tuple of float/int representations
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
    Introspects dynamic metadata for any TA-Lib indicator.
    
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
    return {
        "name": info.get("name", func_name),
        "group": info.get("group", ""),
        "inputs": dict(info.get("input_names", {})),
        "parameters": dict(info.get("parameters", {})),
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
        
        # Determine base types
        if isinstance(default_val, int):
            param_schema["type"] = "integer"
        elif isinstance(default_val, float):
            param_schema["type"] = "number"
        elif isinstance(default_val, bool):
            param_schema["type"] = "boolean"
        else:
            param_schema["type"] = "string"
            
        param_schema["default"] = default_val
        
        # Inject standard range/enum constraints
        if param_name == "matype":
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
                    {"param_name": value, ...},  # Mapping for each column index
                    ...
                ]
            }
        """
        # 1. Fetch cache
        cache_key = make_cache_key(func_name, inputs, params, downcast_float32)
        cached_result = _lru_cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Indicator '{func_name}' hit in LRU cache.")
            return cached_result
            
        # 2. Get Vectorbt indicator class (caches generated classes)
        if func_name not in _indicator_classes:
            _indicator_classes[func_name] = vbt.IndicatorFactory.from_talib(func_name)
        IndicatorClass = _indicator_classes[func_name]
        
        # 3. Resolve input arrays
        run_inputs = resolve_inputs(IndicatorClass, inputs)
        
        # 4. Generate parameter grid (Cartesian product)
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
        
        # 5. Execute calculations in chunks (Memory Limit Guard)
        chunks = [
            combinations[idx:idx + max_param_combinations]
            for idx in range(0, n_combinations, max_param_combinations)
        ]
        
        outputs_list = {out_name: [] for out_name in meta["outputs"]}
        final_columns = None
        
        for chunk in chunks:
            # Reconstruct list of parameter variables for this chunk
            chunk_params = {}
            for idx, p_name in enumerate(param_names):
                chunk_params[p_name] = [c[idx] for c in chunk]
                
            # Run calculations using Vectorbt Pro (param_product=False since we feed it pre-zipped combos)
            res = IndicatorClass.run(**run_inputs, **chunk_params, param_product=False)
            
            # Save intermediate dataframes
            for out_name in meta["outputs"]:
                val_df = pd.DataFrame(getattr(res, out_name))
                outputs_list[out_name].append(val_df)
                
        # 6. Concat chunks and downcast output types
        concat_outputs = {}
        df_columns = None
        for out_name in meta["outputs"]:
            df_concat = pd.concat(outputs_list[out_name], axis=1)
            
            # Track final column index structure
            if df_columns is None:
                df_columns = df_concat.columns
                
            val_array = df_concat.values
            if downcast_float32:
                val_array = val_array.astype(np.float32)
            concat_outputs[out_name] = val_array
            
        # 7. Map column indices back to parameter values
        list_of_param_dicts = []
        if df_columns is not None:
            if isinstance(df_columns, pd.MultiIndex):
                names = df_columns.names
                # Clean names (e.g. remove vbt prefix like 'sma_' from 'sma_timeperiod')
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
                # Single parameter indicator
                name = df_columns.name
                prefix = f"{func_name.lower()}_"
                clean_name = name[len(prefix):] if name and name.startswith(prefix) else name
                for col_val in df_columns:
                    list_of_param_dicts.append({clean_name: col_val})
                    
        result = {
            "outputs": concat_outputs,
            "columns": list_of_param_dicts
        }
        
        # Save cache entry
        _lru_cache.set(cache_key, result)
        return result
