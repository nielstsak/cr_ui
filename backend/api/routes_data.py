import os
import asyncio
import numpy as np
import pandas as pd
import logging
from typing import Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.data.hdf5_storage import HDF5Storage

logger = logging.getLogger("RoutesData")
router = APIRouter()

def get_storage_dir() -> str:
    from backend.api.gateway import app_state
    return app_state.state["configurations"].get("storage_dir", "data")

class OhlcvDataRequest(BaseModel):
    exchange: str = "BINANCE"
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    features: Dict[str, List[str]]

def _execute_hdf5_join(req: OhlcvDataRequest, storage_dir: str) -> dict:
    file_path = os.path.join(storage_dir, req.exchange.upper(), req.symbol.upper().replace("/", ""), req.timeframe.lower(), "ohlcv.h5")
    
    if not os.path.exists(file_path):
        raise ValueError("Fichier de données HDF5 introuvable.")
        
    df_main = None
    
    if "OHLCV" in req.features:
        cols = req.features["OHLCV"]
        with HDF5Storage(file_path, group_path="/OHLCV", mode='r') as st:
            arr = st.read_chunk(req.start_time, req.end_time)
            if len(arr) == 0:
                raise ValueError("Aucune donnée sur cette période.")
            df_main = pd.DataFrame(arr)
            cols_to_keep = ['open_time'] + [c for c in cols if c in df_main.columns]
            df_main = df_main[list(dict.fromkeys(cols_to_keep))]
            
    if df_main is None:
        raise ValueError("Le groupe OHLCV est requis comme axe principal pour la jointure.")

    for group, cols in req.features.items():
        if group.upper() == "OHLCV":
            continue
            
        group_path = f"/{group}" if not group.startswith("/") else group
        try:
            with HDF5Storage(file_path, group_path=group_path, mode='r') as st:
                arr_feat = st.read_chunk(req.start_time, req.end_time)
                if len(arr_feat) > 0:
                    df_feat = pd.DataFrame(arr_feat)
                    cols_to_keep = ['open_time'] + [c for c in cols if c in df_feat.columns]
                    df_feat = df_feat[list(dict.fromkeys(cols_to_keep))]
                    df_main = pd.merge(df_main, df_feat, on='open_time', how='left')
        except Exception as e:
            logger.warning(f"Ignoré: Impossible de joindre le groupe {group_path}. Raison: {e}")

    MAX_POINTS = 2000
    if len(df_main) > MAX_POINTS:
        df_main = df_main.tail(MAX_POINTS).copy()
        
    df_main.replace([np.inf, -np.inf], np.nan, inplace=True)
    df_main = df_main.astype(object).where(pd.notnull(df_main), None)
    
    return df_main.to_dict(orient="list")

@router.post("/api/data/ohlcv")
async def get_ohlcv_data(req: OhlcvDataRequest):
    try:
        storage_dir = get_storage_dir()
        loop = asyncio.get_running_loop()
        data_dict = await loop.run_in_executor(None, _execute_hdf5_join, req, storage_dir)
        return data_dict
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Erreur d'extraction de données: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne lors de l'extraction des données.")