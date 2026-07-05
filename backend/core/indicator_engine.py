# FICHIER : backend/core/indicator_engine.py
import os
import numpy as np
import pandas as pd
import logging
from talib import abstract
from backend.data.hdf5_storage import HDF5Storage

logger = logging.getLogger("IndicatorEngine")

# Colonnes fondamentales intouchables
BASE_COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'quote_vol', 'trades']

def process_and_save_indicators(storage_dir: str, exchange: str, symbol: str, indicators: list):
    """
    Applique une liste d'indicateurs sur TOUS les timeframes d'un symbole.
    Ajoute les indicateurs comme nouvelles colonnes et écrase les fichiers HDF5.
    Si un indicateur n'est plus dans la liste, sa colonne est supprimée.
    """
    symbol_dir = os.path.join(storage_dir, exchange, symbol)
    if not os.path.exists(symbol_dir):
        raise ValueError(f"Le dossier pour le symbole {symbol} n'existe pas.")
        
    tfs = [d for d in os.listdir(symbol_dir) if os.path.isdir(os.path.join(symbol_dir, d))]
    
    for tf in tfs:
        file_path = os.path.join(symbol_dir, tf, "ohlcv.h5")
        if not os.path.exists(file_path):
            continue
            
        try:
            # 1. Lecture du fichier HDF5 actuel
            with HDF5Storage(file_path, exchange, symbol, tf, mode='r') as storage:
                data = storage.read_array(storage.dataset_path)
                
            df = pd.DataFrame(data)
            
            # 2. Purge : On ne garde que les colonnes de base. 
            # Cela garantit que les indicateurs décochés disparaissent.
            available_base_cols = [c for c in BASE_COLS if c in df.columns]
            df = df[available_base_cols]
            
            # 3. Conversion des types pour TA-Lib (exige du float64)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = df[col].astype(np.float64)
                    
            # 4. Calcul dynamique et Ajout des nouvelles colonnes
            for ind_name in indicators:
                try:
                    ind_func = abstract.Function(ind_name.upper())
                    res = ind_func(df)
                    
                    # Gestion des noms de colonnes selon les sorties de l'indicateur (ex: MACD_MACDSIGNAL)
                    out_names = ind_func.info['output_names']
                    
                    if isinstance(res, pd.Series) or (isinstance(res, np.ndarray) and res.ndim == 1):
                        df[ind_name.upper()] = res
                    elif isinstance(res, list) or isinstance(res, tuple):
                        for i, out_arr in enumerate(res):
                            df[f"{ind_name.upper()}_{out_names[i].upper()}"] = out_arr
                    elif isinstance(res, pd.DataFrame):
                        for i, col in enumerate(res.columns):
                            df[f"{ind_name.upper()}_{out_names[i].upper()}"] = res[col]
                            
                except Exception as e:
                    logger.error(f"Erreur lors du calcul de {ind_name} sur {tf}: {e}")
                    
            # 5. Conversion en Records (Tableau structuré NumPy)
            records = df.to_records(index=False)
            
            # 6. Écriture : Suppression du fichier précédent pour redéfinir le schéma HDF5 dynamique
            os.remove(file_path)
            with HDF5Storage(file_path, exchange, symbol, tf, mode='w') as storage:
                storage.write_array(storage.dataset_path, records)
                
            logger.info(f"Indicateurs {indicators} appliqués avec succès au fichier HDF5 ({symbol} {tf}).")
            
        except Exception as e:
            logger.error(f"Erreur globale sur le traitement des indicateurs pour {tf} : {e}")