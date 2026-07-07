import os
import numpy as np
import pandas as pd
import logging
import vectorbtpro as vbt
from talib import get_function_groups
from backend.data.hdf5_storage import HDF5Storage

logger = logging.getLogger("IndicatorEngine")

BASE_COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'quote_vol', 'trades']

def auto_compute_features(storage_dir: str, exchange: str, symbol: str, timeframe: str):
    symbol_dir = os.path.join(storage_dir, exchange.upper(), symbol.upper().replace("/", ""))
    file_path = os.path.join(symbol_dir, timeframe.lower(), "ohlcv.h5")
    
    if not os.path.exists(file_path):
        logger.warning(f"Feature Engineering avorté : Fichier introuvable {file_path}")
        return
        
    try:
        with HDF5Storage(file_path, exchange, symbol, timeframe, mode='r', group_path="/OHLCV") as storage:
            data_arr = storage.read_array(storage.dataset_path)
            
        if len(data_arr) == 0:
            return
            
        df_base = pd.DataFrame(data_arr)
        available_base_cols = [c for c in BASE_COLS if c in df_base.columns]
        df_base = df_base[available_base_cols].copy()
        
        df_base['datetime'] = pd.to_datetime(df_base['open_time'], unit='ms', utc=True)
        df_base.set_index('datetime', inplace=True)
        
        vbt_data = vbt.Data.from_data({symbol: df_base})
        logger.info(f"Démarrage VBT Pro talib_all sur {symbol} ({timeframe})...")
        
        features_df = vbt_data.run("talib_all", skipna=True, concat=True)
        features_df = features_df.reindex(df_base.index)
        
        talib_groups = get_function_groups()
        func_to_group = {func.upper(): group.upper().replace(" ", "_") for group, funcs in talib_groups.items() for func in funcs}
        
        grouped_features = {}
        
        for col in features_df.columns:
            elements = [str(e).upper() for e in col if str(e).upper() != symbol.upper()]
            
            if not elements:
                continue
                
            if elements[0].startswith("TALIB_"):
                elements[0] = elements[0].replace("TALIB_", "")
            
            base_name = elements[0]
            
            if len(elements) > 1 and elements[-1] == 'REAL':
                elements.pop()
                
            col_name = "_".join(elements) if len(elements) > 1 else base_name
            group_name = func_to_group.get(base_name, "UNCATEGORIZED")
            
            if group_name not in grouped_features:
                grouped_features[group_name] = {}
                
            grouped_features[group_name][col_name] = features_df[col].values
            
        open_time_arr = data_arr['open_time']
        
        for group_name, cols_dict in grouped_features.items():
            types = [('open_time', np.int64)]
            arrays = [open_time_arr]
            
            for col_name, val_array in cols_dict.items():
                types.append((col_name, np.float64))
                arrays.append(val_array.astype(np.float64))
                
            structured_dtype = np.dtype(types)
            records = np.empty(len(open_time_arr), dtype=structured_dtype)
            
            records['open_time'] = open_time_arr
            for col_name, val_array in cols_dict.items():
                records[col_name] = val_array
                
            group_path = f"/FEATURES/{group_name}"
            with HDF5Storage(file_path, exchange, symbol, timeframe, mode='a', group_path=group_path) as storage:
                storage.write_array(storage.dataset_path, records)
                
        logger.info(f"Feature Engineering VBT Pro appliqué. Groupes injectés : {list(grouped_features.keys())}")
        
    except Exception as e:
        logger.error(f"Échec critique automatisation indicateurs sur {symbol} ({timeframe}) : {e}")