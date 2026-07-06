# FICHIER : backend/core/indicator_engine.py
import os
import numpy as np
import pandas as pd
import logging
import vectorbtpro as vbt
from backend.data.hdf5_storage import HDF5Storage

logger = logging.getLogger("IndicatorEngine")

# Colonnes fondamentales intouchables
BASE_COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'quote_vol', 'trades']

def auto_compute_features(storage_dir: str, exchange: str, symbol: str, timeframe: str):
    """
    Calcule automatiquement l'intégralité du catalogue TA-Lib via VectorBT Pro (talib_all)
    et met à jour de manière atomique le fichier de stockage HDF5 cible.
    """
    symbol_dir = os.path.join(storage_dir, exchange.upper(), symbol.upper().replace("/", ""))
    file_path = os.path.join(symbol_dir, timeframe.lower(), "ohlcv.h5")
    
    if not os.path.exists(file_path):
        logger.warning(f"Impossible d'exécuter le Feature Engineering : fichier introuvable {file_path}")
        return
        
    try:
        # 1. Lecture du fichier HDF5 actuel
        with HDF5Storage(file_path, exchange, symbol, timeframe, mode='r') as storage:
            data_arr = storage.read_array(storage.dataset_path)
            
        if len(data_arr) == 0:
            return
            
        df = pd.DataFrame(data_arr)
        
        # Purge complète : On réinitialise le DataFrame aux colonnes de base initiales
        available_base_cols = [c for c in BASE_COLS if c in df.columns]
        df_base = df[available_base_cols].copy()
        
        # Préparation de l'index temporel requis par l'API vectorbtpro Data
        df_base['datetime'] = pd.to_datetime(df_base['open_time'], unit='ms')
        df_base.set_index('datetime', inplace=True)
        
        # 2. Instanciation du conteneur de données natif VBT Pro
        vbt_data = vbt.Data.from_data({symbol: df_base})
        
        # 3. Calcul automatisé global haute performance (avec skipna)
        logger.info(f"Démarrage du Feature Engineering natif VectorBT Pro sur {symbol} ({timeframe})...")
        features_df = vbt_data.run("talib_all", skipna=True, concat=True)
        
        # 4. Aplatissement dynamique du MultiIndex généré par VectorBT Pro
        clean_columns = []
        for col in features_df.columns:
            elements = [str(e).upper() for e in col if str(e).upper() != symbol.upper()]
            if elements[0].startswith("TALIB_"):
                elements[0] = elements[0].replace("TALIB_", "")
            
            if len(elements) > 1 and elements[1] == 'REAL':
                col_name = elements[0]
            else:
                col_name = "_".join(elements)
                
            clean_columns.append(col_name)
            
        features_df.columns = clean_columns
        
        # Alignement des index physiques pour la concaténation
        df_base.reset_index(drop=True, inplace=True)
        features_df.reset_index(drop=True, inplace=True)
        final_df = pd.concat([df_base, features_df], axis=1)
        
        # 5. Conversion vers Tableau NumPy Structuré (HDF5)
        types = [(col, final_df[col].dtype) for col in final_df.columns]
        structured_dtype = np.dtype(types)
        records = final_df.to_records(index=False).astype(structured_dtype)
        
        # 6. Écriture atomique
        if os.path.exists(file_path):
            os.remove(file_path)
            
        with HDF5Storage(file_path, exchange, symbol, timeframe, mode='w') as storage:
            storage.write_array(storage.dataset_path, records)
            
        logger.info(f"Feature Engineering VBT Pro appliqué ({symbol} {timeframe}). {len(final_df.columns)} colonnes générées.")
        
    except Exception as e:
        logger.error(f"Échec critique automatisation indicateurs sur {symbol} ({timeframe}) : {e}")