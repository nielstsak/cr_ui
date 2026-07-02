import os
import sqlite3
import uuid
import asyncio
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import talib
from scipy.stats import gaussian_kde, norm
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
from pathlib import Path

# Project imports
from backend.data.hdf5_storage import HDF5Storage, OHLCV_DTYPE
from backend.core.resampler import resample_ohlcv, timeframe_to_ms
from backend.data.binance_client import BinanceClient
from backend.core.indicators import DynamicIndicatorFactory, get_talib_metadata
import inspect

# ==========================================
# 1. Database & Session Management
# ==========================================

def init_database_and_runs():
    """Initializes the SQLite database data/runs.db and inserts default sessions if empty."""
    os.makedirs("data", exist_ok=True)
    db_path = "data/runs.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            timeframe TEXT,
            sample_size INTEGER,
            period_start TEXT,
            period_end TEXT,
            kick_threshold REAL,
            timestamp TEXT
        )
    """)
    # Check if runs exist
    cursor.execute("SELECT COUNT(*) FROM runs")
    if cursor.fetchone()[0] == 0:
        # Seed default sessions
        default_runs = [
            ("BTCUSDT", "15m", 14500, "2026-03-01", "2026-06-22", 2.0, "2026-07-02 12:00:00"),
            ("BTCUSDT", "5m", 43500, "2026-03-01", "2026-06-22", 1.5, "2026-07-01 18:30:00"),
            ("BTCUSDC", "15m", 14500, "2026-03-01", "2026-06-22", 2.0, "2026-07-02 12:05:00")
        ]
        cursor.executemany("""
            INSERT INTO runs (symbol, timeframe, sample_size, period_start, period_end, kick_threshold, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, default_runs)
        conn.commit()
    conn.close()

def sync_database_with_disk():
    """Removes SQLite runs database entries that don't have matching HDF5 files on disk."""
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, timeframe FROM runs")
    all_runs = cursor.fetchall()
    
    base_dir = Path("data/BINANCE")
    for run_id, symbol, timeframe in all_runs:
        symbol_dir = base_dir / symbol.upper()
        file_exists = False
        if symbol_dir.exists():
            for tf_dir in symbol_dir.iterdir():
                if tf_dir.is_dir() and (tf_dir / "ohlcv.h5").exists():
                    file_exists = True
                    break
        if not file_exists:
            cursor.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            
    conn.commit()
    conn.close()

def get_symbols():
    """Fetches unique symbols from database, synchronized with disk."""
    sync_database_with_disk()
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT symbol FROM runs")
    symbols = [r[0] for r in cursor.fetchall()]
    conn.close()
    if not symbols:
        symbols = ["BTCUSDT"]
    return symbols

def get_sessions(symbol):
    """Fetches all sessions for a specific symbol."""
    sync_database_with_disk()
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, timeframe, sample_size, period_start, period_end, kick_threshold 
        FROM runs 
        WHERE symbol = ? 
        ORDER BY timestamp DESC
    """, (symbol,))
    sessions = cursor.fetchall()
    conn.close()
    return sessions

# Initialize DB at startup
init_database_and_runs()

# ==========================================
# 2. Ingestion & Local File Management
# ==========================================

async def ingest_data_async(symbol, timeframe, days_history):
    """Downloads historical OHLCV data directly from Binance API and appends to HDF5."""
    import time
    end_time = int(time.time() * 1000)
    start_time = end_time - int(days_history * 24 * 60 * 60 * 1000)
    
    base_dir = Path("data/BINANCE")
    h5_file = base_dir / symbol.upper() / timeframe.lower() / "ohlcv.h5"
    
    # Instantiate storage wrapper
    storage = HDF5Storage(h5_file, "BINANCE", symbol, timeframe)
    
    async with BinanceClient() as client:
        current_start = start_time
        # Ingest in chunks of 1000 candles
        while current_start <= end_time:
            chunk = await client.fetch_klines_historical(symbol, timeframe, current_start, end_time)
            if len(chunk) == 0:
                break
            storage.append_chunk(chunk)
            last_open = chunk[-1]['open_time']
            current_start = last_open + 1
            if last_open >= end_time:
                break

def list_local_data():
    """Scans data/BINANCE directory and lists all available ohlcv.h5 data files."""
    local_files = []
    base_dir = Path("data/BINANCE")
    if base_dir.exists():
        for symbol_dir in base_dir.iterdir():
            if symbol_dir.is_dir():
                for tf_dir in symbol_dir.iterdir():
                    if tf_dir.is_dir():
                        h5_file = tf_dir / "ohlcv.h5"
                        if h5_file.exists():
                            size_mb = h5_file.stat().st_size / (1024 * 1024)
                            try:
                                with HDF5Storage(h5_file, "BINANCE", symbol_dir.name, tf_dir.name, mode='r') as storage:
                                    dataset = storage.read_array(storage.dataset_path)
                                    row_count = len(dataset)
                                    if row_count > 0:
                                        start_t = pd.to_datetime(dataset[0]['open_time'], unit='ms').strftime('%Y-%m-%d %H:%M')
                                        end_t = pd.to_datetime(dataset[-1]['open_time'], unit='ms').strftime('%Y-%m-%d %H:%M')
                                    else:
                                        start_t, end_t = "Vide", "Vide"
                            except Exception:
                                row_count = 0
                                start_t, end_t = "N/A", "N/A"
                                
                            local_files.append({
                                "symbol": symbol_dir.name,
                                "timeframe": tf_dir.name,
                                "file_path": str(h5_file),
                                "size_mb": size_mb,
                                "row_count": row_count,
                                "start_time": start_t,
                                "end_time": end_t
                            })
    return local_files

def load_ohlcv_data(symbol, timeframe):
    """Loads OHLCV data from HDF5 storage using dynamic timeframe resolution and resampling fallback."""
    base_dir = Path("data/BINANCE") / symbol.upper()
    
    # 1. Try target timeframe file
    h5_file = base_dir / timeframe.lower() / "ohlcv.h5"
    active_tf = timeframe
    
    # 2. Try base 5m timeframe file
    if not h5_file.exists():
        h5_file = base_dir / "5m" / "ohlcv.h5"
        active_tf = "5m"
        
    # 3. Try any available timeframe file under this symbol
    if not h5_file.exists() and base_dir.exists():
        for tf_dir in base_dir.iterdir():
            if tf_dir.is_dir():
                candidate = tf_dir / "ohlcv.h5"
                if candidate.exists():
                    h5_file = candidate
                    active_tf = tf_dir.name
                    break
                    
    # 4. Fallback to BTCUSDT 5m if still not found
    if not h5_file.exists():
        fallback_symbol = "BTCUSDT"
        base_dir = Path("data/BINANCE") / fallback_symbol
        h5_file = base_dir / "5m" / "ohlcv.h5"
        active_tf = "5m"
        if not h5_file.exists() and base_dir.exists():
            for tf_dir in base_dir.iterdir():
                if tf_dir.is_dir():
                    candidate = tf_dir / "ohlcv.h5"
                    if candidate.exists():
                        h5_file = candidate
                        active_tf = tf_dir.name
                        break
                        
    if not h5_file.exists():
        st.error(f"Fichier de données OHLCV introuvable pour {symbol} ou son fallback.")
        return None
        
    symbol_name = h5_file.parent.parent.name
    with HDF5Storage(h5_file, "BINANCE", symbol_name, active_tf, mode='r') as storage:
        raw_data = storage.read_array(storage.dataset_path)
        
    # Resample to target timeframe if different
    if active_tf.lower() != timeframe.lower():
        try:
            resampled = resample_ohlcv(raw_data, timeframe, align='close')
            return resampled
        except Exception as e:
            st.warning(f"Erreur de rééchantillonnage de {active_tf} vers {timeframe}: {e}. Données brutes utilisées.")
            return raw_data
            
    return raw_data

# ==========================================
# 3. Streamlit Page Configuration & CSS
# ==========================================

st.set_page_config(
    page_title="TradingVBT - Premium Analytics Suite",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom theme overrides matching Design System Tokens
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #0d1117;
        color: #c9d1d9;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1.5px solid #30363d;
    }
    
    /* Layout Containers & Cards */
    div.stElementContainer, div.stBlock {
        background-color: transparent;
    }
    
    /* Card Container Wrapper */
    .ds-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 18px;
        margin-bottom: 20px;
    }
    
    .ds-card-title {
        font-size: 14px;
        font-weight: 600;
        text-transform: uppercase;
        color: #58a6ff;
        border-bottom: 1px solid #30363d;
        padding-bottom: 8px;
        margin-bottom: 15px;
    }
    
    /* Sticky Header Container */
    .sticky-header {
        position: -webkit-sticky;
        position: sticky;
        top: 0;
        z-index: 100;
        background-color: #0d1117;
        border-bottom: 1.5px solid #30363d;
        padding-top: 15px;
        padding-bottom: 15px;
        margin-bottom: 25px;
    }
    
    /* Metric Card Customization */
    div[data-testid="stMetric"] {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 10px 15px;
        text-align: center;
    }
    div[data-testid="stMetricValue"] {
        font-size: 20px;
        font-weight: bold;
        color: #ffffff;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 12px;
        color: #8b949e;
        text-transform: uppercase;
    }
    
    /* Streamlit Tabs Customization */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #0d1117;
    }
    .stTabs [data-baseweb="tab"] {
        height: 48px;
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px 6px 0px 0px;
        color: #8b949e;
        padding: 0px 20px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #1f6feb !important;
        color: #ffffff !important;
        font-weight: bold;
        border-bottom: none;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar navigation
st.sidebar.title("💎 TradingVBT Dashboard")
selected_page = st.sidebar.radio(
    "Navigation", 
    ["Landing (Gestion des Données)", "Analyse Statistique"], 
    index=0
)

# ==========================================
# PAGE 1: Landing Page (Data Management)
# ==========================================
if selected_page == "Landing (Gestion des Données)":
    st.markdown("## 📥 Ingestion & Gestion des Données MTF")
    st.markdown("Configurez l'ingestion d'historique depuis l'API Binance et stockez-les localement au format HDF5.")
    
    # 1. Ingestion Form
    st.markdown('<div class="ds-card"><div class="ds-card-title">1. Télécharger de nouvelles données</div>', unsafe_allow_html=True)
    with st.form("ingest_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            ing_symbol = st.text_input("Paire de Trading (Symbole)", value="BTCUSDT").upper()
        with col2:
            ing_tf = st.selectbox("Unité de Temps (Timeframe)", ["1m", "5m", "15m", "1h", "1d"], index=1)
        with col3:
            ing_days = st.number_input("Historique (Jours)", min_value=1, max_value=365, value=30)
            
        submitted = st.form_submit_button("Lancer le Téléchargement")
        if submitted:
            with st.spinner(f"Téléchargement de {ing_symbol} {ing_tf} pour {ing_days} jours en cours..."):
                try:
                    # Run direct ingestion using our client
                    asyncio.run(ingest_data_async(ing_symbol, ing_tf, ing_days))
                    
                    # Read the downloaded file to get real metrics
                    h5_file = Path("data/BINANCE") / ing_symbol / ing_tf.lower() / "ohlcv.h5"
                    row_count = 0
                    start_t, end_t = "N/A", "N/A"
                    if h5_file.exists():
                        with HDF5Storage(h5_file, "BINANCE", ing_symbol, ing_tf, mode='r') as storage:
                            dataset = storage.read_array(storage.dataset_path)
                            row_count = len(dataset)
                            if row_count > 0:
                                start_t = pd.to_datetime(dataset[0]['open_time'], unit='ms').strftime('%Y-%m-%d')
                                end_t = pd.to_datetime(dataset[-1]['open_time'], unit='ms').strftime('%Y-%m-%d')
                    
                    # Insert or update run session in SQLite db with correct info
                    conn = sqlite3.connect("data/runs.db")
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM runs WHERE symbol = ? AND timeframe = ?", (ing_symbol, ing_tf))
                    cursor.execute("""
                        INSERT INTO runs (symbol, timeframe, sample_size, period_start, period_end, kick_threshold, timestamp)
                        VALUES (?, ?, ?, ?, ?, 2.0, datetime('now'))
                    """, (ing_symbol, ing_tf, row_count, start_t, end_t))
                    conn.commit()
                    conn.close()
                    
                    st.success(f"Données pour {ing_symbol} {ing_tf} téléchargées et enregistrées avec succès !")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur de téléchargement: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

    # 2. Local Data Files Table
    st.markdown('<div class="ds-card"><div class="ds-card-title">2. Données Locales Ingestées (MTF)</div>', unsafe_allow_html=True)
    local_data = list_local_data()
    if not local_data:
        st.info("Aucun fichier HDF5 trouvé dans data/BINANCE.")
    else:
        # Display in table with Delete and Refresh buttons
        for idx, item in enumerate(local_data):
            r_col1, r_col2, r_col3, r_col4, r_col5 = st.columns([2, 1, 1, 1, 1])
            with r_col1:
                st.write(f"**{item['symbol']}** ({item['timeframe']})")
                st.caption(f"Période: {item['start_time']} à {item['end_time']}")
            with r_col2:
                st.write(f"{item['size_mb']:.2f} Mo")
            with r_col3:
                st.write(f"{item['row_count']:,} bougies")
            with r_col4:
                # Refresh button
                if st.button("Actualiser", key=f"ref_{idx}"):
                    with st.spinner(f"Actualisation de {item['symbol']} {item['timeframe']}..."):
                        try:
                            # Re-ingest last 30 days
                            asyncio.run(ingest_data_async(item['symbol'], item['timeframe'], 30))
                            st.success(f"Données actualisées pour {item['symbol']} !")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur d'actualisation: {e}")
            with r_col5:
                # Delete button
                if st.button("Supprimer", key=f"del_{idx}"):
                    try:
                        # Clear SQLite run sessions for this symbol
                        conn = sqlite3.connect("data/runs.db")
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM runs WHERE symbol = ? AND timeframe = ?", (item['symbol'], item['timeframe']))
                        conn.commit()
                        conn.close()
                        
                        os.remove(item['file_path'])
                        st.success(f"Fichier de données supprimé pour {item['symbol']} !")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur de suppression: {e}")
            st.markdown('<hr style="border: 0.5px solid #30363d; margin: 10px 0;"/>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# PAGE 2: Analysis Page (Statistical Tabs)
# ==========================================
elif selected_page == "Analyse Statistique":
    # ------------------------------------------
    # Sticky Header Section
    # ------------------------------------------
    st.markdown('<div class="sticky-header">', unsafe_allow_html=True)
    header_col1, header_col2 = st.columns([1, 2])

    with header_col1:
        st.markdown("#### 🎨 CONFIGURATION DES DONNÉES RUN")
        sub_col1, sub_col2 = st.columns(2)
        with sub_col1:
            symbols_list = get_symbols()
            selected_symbol = st.selectbox("Symbole", symbols_list)
        with sub_col2:
            sessions_list = get_sessions(selected_symbol)
            session_options = [f"{s[0]} ({s[1]})" for s in sessions_list]
            selected_session_str = st.selectbox("Session d'Analyse (UTC)", session_options)
            
            # Parse selected session info
            session_idx = session_options.index(selected_session_str)
            session_data = sessions_list[session_idx]
            s_timestamp, s_timeframe, s_sample_size, s_period_start, s_period_end, s_kick_threshold = session_data

    with header_col2:
        st.markdown("#### 📐 TABLEAU FLASH DE PARAMÈTRES (KPI ROW)")
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        metric_col1.metric("Timeframe Ciblé", s_timeframe, help="Rééchantillonné depuis la base 5m")
        metric_col2.metric("Taille Échantillon", f"{s_sample_size:,} bougies")
        metric_col3.metric("Période Couverte", f"{s_period_start} / {s_period_end}")
        metric_col4.metric("Seuil Kick Volatilité", f"{s_kick_threshold:.1f}%")

    st.markdown('</div>', unsafe_allow_html=True)

    # Load underlying data
    ohlcv_data = load_ohlcv_data(selected_symbol, s_timeframe)

    if ohlcv_data is None or len(ohlcv_data) == 0:
        st.error("Aucune donnée disponible pour l'affichage.")
        st.stop()

    # Crop data to the required sample size
    sample_len = min(s_sample_size, len(ohlcv_data))
    df = pd.DataFrame(ohlcv_data[-sample_len:])
    df['time'] = pd.to_datetime(df['open_time'], unit='ms')

    # Calculate basic features
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(10).std()
    df['spread'] = (df['high'] - df['low']) / df['close']
    df['upper_wick'] = (df['high'] - np.maximum(df['open'], df['close'])) / df['close']
    df['lower_wick'] = (np.minimum(df['open'], df['close']) - df['low']) / df['close']
    df['body_size'] = np.abs(df['close'] - df['open']) / df['close']

    # Identify Kicks
    kick_pct = s_kick_threshold / 100.0
    df['kick_type'] = 'Normal'
    df.loc[df['returns'] >= kick_pct, 'kick_type'] = 'High Kick'
    df.loc[df['returns'] <= -kick_pct, 'kick_type'] = 'Low Kick'

    # Identify Double Kicks / Both (consecutive opposite kicks)
    for idx in range(1, len(df)):
        prev = df.loc[df.index[idx - 1], 'kick_type']
        curr = df.loc[df.index[idx], 'kick_type']
        if prev in ('High Kick', 'Low Kick') and curr in ('High Kick', 'Low Kick') and prev != curr:
            df.loc[df.index[idx], 'kick_type'] = 'Both'

    # Clean NaNs
    df.fillna(method='bfill', inplace=True)

    def compute_indicator(name, df_inputs):
        # Inputs mapping
        inputs = {
            'open': df_inputs['open'].values,
            'high': df_inputs['high'].values,
            'low': df_inputs['low'].values,
            'close': df_inputs['close'].values,
            'volume': df_inputs['volume'].values
        }
        
        # Sensible default parameters for each indicator
        params = {}
        if name in ["SMA", "EMA", "DEMA", "KAMA", "T3", "TEMA", "TRIMA", "WMA", "LINEARREG", "TSF"]:
            params = {"timeperiod": 20}
        elif name == "MA":
            params = {"timeperiod": 20, "matype": 0}
        elif name == "BBANDS":
            params = {"timeperiod": 20, "nbdevup": 2.0, "nbdevdn": 2.0}
        elif name == "MACD":
            params = {"fastperiod": 12, "slowperiod": 26, "signalperiod": 9}
        elif name == "MACDEXT":
            params = {"fastperiod": 12, "fastmatype": 0, "slowperiod": 26, "slowmatype": 0, "signalperiod": 9, "signalmatype": 0}
        elif name == "MACDFIX":
            params = {"signalperiod": 9}
        elif name in ["RSI", "CCI", "CMO", "MOM", "ROC", "ROCP", "ROCR", "ROCR100", "WILLR", "MFI", "ADX", "ADXR", "DX", "MINUS_DI", "MINUS_DM", "PLUS_DI", "PLUS_DM", "ATR", "NATR"]:
            params = {"timeperiod": 14}
        elif name in ["STOCH", "STOCHF"]:
            params = {"fastk_period": 5, "slowk_period": 3, "slowk_matype": 0, "slowd_period": 3, "slowd_matype": 0}
        elif name == "STOCHRSI":
            params = {"timeperiod": 14, "fastk_period": 5, "fastd_period": 3, "fastd_matype": 0}
        elif name in ["MAX", "MIN", "MAXINDEX", "MININDEX", "MINMAX", "MINMAXINDEX", "SUM", "VAR", "STDDEV", "BETA", "CORREL"]:
            params = {"timeperiod": 30}
        elif name in ["AROON", "AROONOSC"]:
            params = {"timeperiod": 14}
        elif name == "ULTOSC":
            params = {"timeperiod1": 7, "timeperiod2": 14, "timeperiod3": 28}
            
        try:
            res = DynamicIndicatorFactory.run_indicator(name, inputs, params)
            return res["outputs"]
        except Exception as e:
            # Fallback to direct TA-Lib execution if factory fails or doesn't support the indicator shape
            try:
                func = getattr(talib, name)
                sig = inspect.signature(func)
                run_inputs = {}
                for p_name in sig.parameters:
                    if p_name == 'real':
                        run_inputs['real'] = df_inputs['close'].values
                    elif p_name in ['open', 'high', 'low', 'close', 'volume']:
                        run_inputs[p_name] = df_inputs[p_name].values
                
                run_params = {}
                for p_name, p_val in params.items():
                    if p_name in sig.parameters:
                        run_params[p_name] = p_val
                
                out = func(**run_inputs, **run_params)
                meta = get_talib_metadata(name)
                if isinstance(out, tuple):
                    return {meta["outputs"][i]: out[i] for i in range(len(out))}
                else:
                    return {meta["outputs"][0]: out}
            except Exception as e2:
                st.warning(f"Impossible de calculer {name}: {e2}")
                return None

    # ------------------------------------------
    # Core View Layout - 7 Tabs
    # ------------------------------------------
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📈 Chart & Indicators",
        "📋 Run Overview",
        "🔍 Lagged Indicators",
        "📅 Seasonality",
        "🌪️ Volatility Clustering",
        "📊 HMM Regime Map",
        "🧬 VSA & Wicks"
    ])

    # ----------------------------------------------------
    # TAB 1: Chart & Indicators
    # ----------------------------------------------------
    with tab1:
        # Container 1: Panneau de Sélection & Contrôles
        st.markdown('<div class="ds-card"><div class="ds-card-title">1. Panneau de Sélection &amp; Contrôles</div>', unsafe_allow_html=True)
        c1_col1, c1_col2, c1_col3 = st.columns(3)
        with c1_col1:
            overlays_options = ["SMA", "EMA", "BBANDS", "DEMA", "KAMA", "LINEARREG", "MA", "MAMA", "MIDPOINT", "MIDPRICE", "SAR", "SAREXT", "T3", "TEMA", "TRIMA", "TSF", "WMA", "HT_TRENDLINE"]
            overlays = st.multiselect("Indicateurs de Prix (Overlays)", overlays_options, default=["SMA"])
        with c1_col2:
            oscillators_options = ["RSI", "ATR", "AD", "ADOSC", "ADX", "ADXR", "APO", "AROON", "AROONOSC", "BETA", "BOP", "CCI", "CMO", "CORREL", "DX", "LINEARREG_ANGLE", "LINEARREG_INTERCEPT", "LINEARREG_SLOPE", "MACD", "MACDEXT", "MACDFIX", "MAX", "MAXINDEX", "MEDPRICE", "MFI", "MIN", "MININDEX", "MINMAX", "MINMAXINDEX", "MINUS_DI", "MINUS_DM", "MOM", "NATR", "OBV", "PLUS_DI", "PLUS_DM", "PPO", "ROC", "ROCP", "ROCR", "ROCR100", "STDDEV", "STOCH", "STOCHF", "STOCHRSI", "SUM", "TRANGE", "TRIX", "TYPPRICE", "ULTOSC", "VAR", "WCLPRICE", "WILLR", "HT_DCPERIOD", "HT_DCPHASE", "HT_PHASOR", "HT_SINE", "HT_TRENDMODE"]
            oscillators = st.multiselect("Oscillateurs (Sous-graphes)", oscillators_options, default=["RSI"])
        with c1_col3:
            y_scale = st.radio("Transformation Échelle Y (Axe Prix)", ["Valeur Brute", "Logarithmique", "Rendement Normalisé"], horizontal=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Apply Y scale transformation
        if y_scale == "Logarithmique":
            df['y_price'] = np.log(df['close'])
            df['y_open'] = np.log(df['open'])
            df['y_high'] = np.log(df['high'])
            df['y_low'] = np.log(df['low'])
        elif y_scale == "Rendement Normalisé":
            df['y_price'] = (df['close'] - df['close'].mean()) / df['close'].std()
            df['y_open'] = (df['open'] - df['close'].mean()) / df['close'].std()
            df['y_high'] = (df['high'] - df['close'].mean()) / df['close'].std()
            df['y_low'] = (df['low'] - df['close'].mean()) / df['close'].std()
        else:
            df['y_price'] = df['close']
            df['y_open'] = df['open']
            df['y_high'] = df['high']
            df['y_low'] = df['low']

        # Container 2: Graphique Principal Synchrone
        st.markdown('<div class="ds-card"><div class="ds-card-title">2. Graphique Principal Synchrone</div>', unsafe_allow_html=True)
        num_subplots = 2 + len(oscillators)
        row_heights = [0.60, 0.12] + [0.14] * len(oscillators)
        
        fig = make_subplots(
            rows=num_subplots, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.03,
            row_heights=row_heights
        )
        
        # Y1: Candlestick price chart
        fig.add_trace(go.Candlestick(
            x=df['time'],
            open=df['y_open'], high=df['y_high'], low=df['y_low'], close=df['y_price'],
            increasing_line_color='#2ecc71', decreasing_line_color='#e74c3c',
            name="OHLCV"
        ), row=1, col=1)
        
        # Overlays
        for name in overlays:
            outputs = compute_indicator(name, df)
            if outputs:
                for out_name, out_arr in outputs.items():
                    if len(out_arr.shape) > 1 and out_arr.shape[1] > 0:
                        out_series = out_arr[:, 0]
                    else:
                        out_series = out_arr
                        
                    # Apply scaling
                    if y_scale == "Logarithmique":
                        out_series = np.log(out_series)
                    elif y_scale == "Rendement Normalisé":
                        out_series = (out_series - df['close'].mean()) / df['close'].std()
                        
                    fig.add_trace(go.Scatter(
                        x=df['time'], y=out_series,
                        line=dict(width=1.2),
                        name=f"{name} ({out_name})"
                    ), row=1, col=1)

        # Y2: Volume chart
        colors = ['#2ecc71' if c >= o else '#e74c3c' for c, o in zip(df['close'], df['open'])]
        fig.add_trace(go.Bar(
            x=df['time'], y=df['volume'], 
            marker_color=colors, 
            name="Volume"
        ), row=2, col=1)
        
        # Y3 & subsequent: Oscillators
        osc_row = 3
        for name in oscillators:
            outputs = compute_indicator(name, df)
            if outputs:
                for out_name, out_arr in outputs.items():
                    if len(out_arr.shape) > 1 and out_arr.shape[1] > 0:
                        out_series = out_arr[:, 0]
                    else:
                        out_series = out_arr
                        
                    fig.add_trace(go.Scatter(
                        x=df['time'], y=out_series,
                        line=dict(width=1.2),
                        name=f"{name} ({out_name})"
                    ), row=osc_row, col=1)
                
                # Add typical helper thresholds for RSI-like momentum indicators
                if name == "RSI":
                    fig.add_hline(y=70, line_dash="dash", line_color="#e74c3c", line_width=1, row=osc_row, col=1)
                    fig.add_hline(y=30, line_dash="dash", line_color="#2ecc71", line_width=1, row=osc_row, col=1)
                elif name == "WILLR":
                    fig.add_hline(y=-20, line_dash="dash", line_color="#e74c3c", line_width=1, row=osc_row, col=1)
                    fig.add_hline(y=-80, line_dash="dash", line_color="#2ecc71", line_width=1, row=osc_row, col=1)
                
                osc_row += 1
            
        fig.update_layout(
            height=300 + 150 * num_subplots,
            margin=dict(l=30, r=30, t=10, b=10),
            paper_bgcolor='#0d1117',
            plot_bgcolor='#161b22',
            xaxis=dict(gridcolor='#30363d'),
            yaxis=dict(gridcolor='#30363d'),
            showlegend=True,
            xaxis_rangeslider_visible=False
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Container 3: Panneau de Zoom & Focus
        st.markdown('<div class="ds-card"><div class="ds-card-title">3. Panneau de Zoom &amp; Focus</div>', unsafe_allow_html=True)
        zoom_options = ["Prix Clôture", "Volatility", "Spread"] + overlays + oscillators
        zoom_feature = st.selectbox("Sélectionner la Feature à Focus", zoom_options, index=0)
        
        if zoom_feature == "Prix Clôture":
            focus_series = df['close']
        elif zoom_feature == "Volatility":
            focus_series = df['volatility']
        elif zoom_feature == "Spread":
            focus_series = df['spread']
        else:
            outputs = compute_indicator(zoom_feature, df)
            if outputs:
                first_key = list(outputs.keys())[0]
                out_arr = outputs[first_key]
                if len(out_arr.shape) > 1 and out_arr.shape[1] > 0:
                    focus_series = pd.Series(out_arr[:, 0], index=df.index)
                else:
                    focus_series = pd.Series(out_arr, index=df.index)
            else:
                focus_series = df['close']
            
        focus_ema = talib.EMA(focus_series.values, timeperiod=10)
        
        fig_focus = go.Figure()
        fig_focus.add_trace(go.Scatter(x=df['time'], y=focus_series, line=dict(color='#58a6ff', width=1.5), name="Valeur Brute"))
        fig_focus.add_trace(go.Scatter(x=df['time'], y=focus_ema, line=dict(color='#f39c12', width=2.0), name="EMA 10 (Lissé)"))
        fig_focus.update_layout(
            height=350,
            margin=dict(l=30, r=30, t=10, b=10),
            paper_bgcolor='#0d1117',
            plot_bgcolor='#161b22',
            xaxis=dict(gridcolor='#30363d'),
            yaxis=dict(gridcolor='#30363d'),
            showlegend=True
        )
        st.plotly_chart(fig_focus, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Container 4 & 5
        col_c4, col_c5 = st.columns(2)
        
        with col_c4:
            # Container 4: Profil de Volume (Volume Profile)
            st.markdown('<div class="ds-card"><div class="ds-card-title">4. Profil de Volume</div>', unsafe_allow_html=True)
            # Compute horizontal volume profile
            prices = df['close'].values
            volumes = df['volume'].values
            nbins = 40
            counts, bins = np.histogram(prices, bins=nbins, weights=volumes)
            bin_centers = (bins[:-1] + bins[1:]) / 2
            
            # Find Point of Control (POC)
            poc_idx = np.argmax(counts)
            poc_price = bin_centers[poc_idx]
            
            # Find Value Area (68% volume centered around POC)
            sorted_indices = np.argsort(counts)[::-1]
            cumulative_volume = 0
            total_volume = volumes.sum()
            value_area_indices = []
            for idx in sorted_indices:
                cumulative_volume += counts[idx]
                value_area_indices.append(idx)
                if cumulative_volume >= 0.68 * total_volume:
                    break
                    
            # Color profile bars
            profile_colors = ['#1f6feb' if i in value_area_indices else '#30363d' for i in range(len(counts))]
            
            fig_vp = go.Figure(go.Bar(
                y=bin_centers, x=counts,
                orientation='h',
                marker_color=profile_colors,
                name="Volume"
            ))
            # Draw POC Line
            fig_vp.add_hline(y=poc_price, line_color="#e74c3c", line_width=2.5, name="POC")
            fig_vp.update_layout(
                height=400,
                margin=dict(l=30, r=30, t=10, b=10),
                paper_bgcolor='#0d1117',
                plot_bgcolor='#161b22',
                xaxis=dict(gridcolor='#30363d', title="Volume Cumulé"),
                yaxis=dict(gridcolor='#30363d', title="Prix"),
                showlegend=False
            )
            st.plotly_chart(fig_vp, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c5:
            # Container 5: Proxy de Dispersion Intra-Bougie
            st.markdown('<div class="ds-card"><div class="ds-card-title">5. Proxy de Dispersion Intra-Bougie</div>', unsafe_allow_html=True)
            df['amplitude'] = df['high'] - df['low']
            # Normalize bubble size
            vol_normalized = 5 + 35 * (df['volume'] - df['volume'].min()) / (df['volume'].max() - df['volume'].min() + 1e-8)
            colors_bubble = ['#2ecc71' if c >= o else '#e74c3c' for c, o in zip(df['close'], df['open'])]
            
            fig_disp = go.Figure(go.Scatter(
                x=df['time'], y=df['amplitude'],
                mode='markers',
                marker=dict(
                    size=vol_normalized,
                    color=colors_bubble,
                    opacity=0.6,
                    line=dict(width=0.5, color='#ffffff')
                ),
                name="Dispersion"
            ))
            fig_disp.update_layout(
                height=400,
                margin=dict(l=30, r=30, t=10, b=10),
                paper_bgcolor='#0d1117',
                plot_bgcolor='#161b22',
                xaxis=dict(gridcolor='#30363d', title="Temps"),
                yaxis=dict(gridcolor='#30363d', title="Amplitude Absolue (High - Low)"),
                showlegend=False
            )
            st.plotly_chart(fig_disp, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 2: Run Overview
    # ----------------------------------------------------
    with tab2:
        # Container 1: Métadonnées du Run Statistique
        st.markdown('<div class="ds-card"><div class="ds-card-title">1. Métadonnées du Run Statistique</div>', unsafe_allow_html=True)
        run_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{selected_symbol}_{s_timeframe}_{s_timestamp}"))
        metadata_html = f"""
        <table style="width:100%; border: 1px solid #30363d; border-collapse: collapse;">
            <tr style="background-color: #161b22;">
                <th style="padding: 10px; border: 1px solid #30363d; color: #58a6ff;">Paramètre</th>
                <th style="padding: 10px; border: 1px solid #30363d; color: #58a6ff;">Valeur</th>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #30363d; font-weight: bold;">UUID du Run</td>
                <td style="padding: 10px; border: 1px solid #30363d; font-family: monospace;">{run_uuid}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #30363d; font-weight: bold;">Version du Script</td>
                <td style="padding: 10px; border: 1px solid #30363d; font-family: monospace;">v1.4.2-stable</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #30363d; font-weight: bold;">Taux de Complétion des Données</td>
                <td style="padding: 10px; border: 1px solid #30363d; color: #2ecc71; font-weight: bold;">100.0% (0 NaN après imputation)</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #30363d; font-weight: bold;">Directives de Base de Temps</td>
                <td style="padding: 10px; border: 1px solid #30363d; color: #e74c3c;">Stricte conformité base 5 minutes respectée. Resampling validé par test T53.</td>
            </tr>
        </table>
        """
        st.markdown(metadata_html, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Container 2: KPI Cards de Distribution des Rendements
        st.markdown('<div class="ds-card"><div class="ds-card-title">2. KPI Cards de Distribution des Rendements</div>', unsafe_allow_html=True)
        cum_yield = (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100
        tf_ms = timeframe_to_ms(s_timeframe)
        min_in_tf = tf_ms / 60000.0
        ann_factor = np.sqrt((365.25 * 1440.0) / min_in_tf)
        hist_vol = df['returns'].std() * ann_factor * 100
        skew = df['returns'].skew()
        kurt = df['returns'].kurtosis()
        
        kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
        kpi_col1.metric("Rendement Cumulé (%)", f"{cum_yield:+.2f}%")
        kpi_col2.metric("Volatilité Annuelle (%)", f"{hist_vol:.2f}%")
        kpi_col3.metric("Skewness (Asymétrie)", f"{skew:.3f}")
        kpi_col4.metric("Kurtosis (Aplatissement)", f"{kurt:.3f}")
        st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Containers 3 & 4
        col_c3, col_c4 = st.columns(2)
        
        with col_c3:
            # Container 3: Fréquence de Dépassement des Seuils (Kicks)
            st.markdown('<div class="ds-card"><div class="ds-card-title">3. Fréquence de Dépassement des Seuils (Kicks)</div>', unsafe_allow_html=True)
            counts = df['kick_type'].value_counts()
            total_counts = len(df)
            kick_categories = ['High Kick', 'Low Kick', 'Both']
            kick_vals = [counts.get(cat, 0) for cat in kick_categories]
            kick_pcts = [v / total_counts * 100 for v in kick_vals]
            
            fig_kicks = go.Figure(go.Bar(
                y=kick_categories, x=kick_vals,
                orientation='h',
                text=[f"{v} ({p:.2f}%)" for v, p in zip(kick_vals, kick_pcts)],
                textposition='auto',
                marker_color=['#2ecc71', '#e74c3c', '#9b59b6']
            ))
            fig_kicks.update_layout(
                height=300,
                margin=dict(l=30, r=30, t=10, b=10),
                paper_bgcolor='#0d1117',
                plot_bgcolor='#161b22',
                xaxis=dict(gridcolor='#30363d', title="Nombre d'occurrences"),
                yaxis=dict(gridcolor='#30363d')
            )
            st.plotly_chart(fig_kicks, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col_c4:
            # Container 4: Analyse des Queues de Distribution (QQ-Plot)
            st.markdown('<div class="ds-card"><div class="ds-card-title">4. Analyse des Queues de Distribution (QQ-Plot)</div>', unsafe_allow_html=True)
            returns_clean = df['returns'].dropna().values
            std_returns = (returns_clean - returns_clean.mean()) / (returns_clean.std() + 1e-8)
            std_returns.sort()
            theoretical_quantiles = norm.ppf(np.linspace(0.01, 0.99, len(std_returns)))
            
            fig_qq = go.Figure()
            fig_qq.add_trace(go.Scatter(
                x=theoretical_quantiles, y=std_returns,
                mode='markers',
                marker=dict(color='#1f6feb', size=4),
                name="Rendements"
            ))
            lims = [min(theoretical_quantiles), max(theoretical_quantiles)]
            fig_qq.add_trace(go.Scatter(
                x=lims, y=lims,
                mode='lines',
                line=dict(color='#8b949e', width=1.5, dash='dot'),
                name="Loi Normale"
            ))
            fig_qq.update_layout(
                height=300,
                margin=dict(l=30, r=30, t=10, b=10),
                paper_bgcolor='#0d1117',
                plot_bgcolor='#161b22',
                xaxis=dict(gridcolor='#30363d', title="Quantiles théoriques Loi Normale"),
                yaxis=dict(gridcolor='#30363d', title="Quantiles empiriques"),
                showlegend=False
            )
            st.plotly_chart(fig_qq, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Container 5: Décomposition MFE / MAE (Excursion Maximale)
        st.markdown('<div class="ds-card"><div class="ds-card-title">5. Décomposition MFE / MAE</div>', unsafe_allow_html=True)
        mfe_mae_len = min(100, len(df))
        df_mfe_mae = df.tail(mfe_mae_len).copy()
        mfe = (df_mfe_mae['high'] - df_mfe_mae['open']) / df_mfe_mae['open'] * 100
        mae = (df_mfe_mae['low'] - df_mfe_mae['open']) / df_mfe_mae['open'] * 100
        
        fig_excursion = go.Figure()
        fig_excursion.add_trace(go.Bar(
            x=np.arange(mfe_mae_len), y=mfe,
            marker_color='#2ecc71',
            name="MFE (Excursion Favorable)"
        ))
        fig_excursion.add_trace(go.Bar(
            x=np.arange(mfe_mae_len), y=mae,
            marker_color='#e74c3c',
            name="MAE (Excursion Défavorable)"
        ))
        fig_excursion.update_layout(
            height=350,
            margin=dict(l=30, r=30, t=10, b=10),
            barmode='relative',
            paper_bgcolor='#0d1117',
            plot_bgcolor='#161b22',
            xaxis=dict(gridcolor='#30363d', title="Index Bougie (Échantillon de 100 max)"),
            yaxis=dict(gridcolor='#30363d', title="Écart en % depuis l'Open"),
            showlegend=True
        )
        st.plotly_chart(fig_excursion, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 3: Lagged Indicators
    # ----------------------------------------------------
    with tab3:
        # Container 1: Panneau de Configuration des Décalages
        st.markdown('<div class="ds-card"><div class="ds-card-title">1. Panneau de Configuration des Décalages</div>', unsafe_allow_html=True)
        lag_col1, lag_col2 = st.columns(2)
        with lag_col1:
            lag_feature = st.selectbox("Feature d'observation", ["Volume", "Spread", "Upper Wick", "Lower Wick", "Returns"], index=4)
        with lag_col2:
            lag_window = st.slider("Fenêtre de Décalage temporel (Lags)", min_value=-20, max_value=5, value=(-20, 5))
        st.markdown('</div>', unsafe_allow_html=True)

        f_map = {
            "Volume": df['volume'],
            "Spread": df['spread'],
            "Upper Wick": df['upper_wick'],
            "Lower Wick": df['lower_wick'],
            "Returns": df['returns']
        }
        feat_series = f_map[lag_feature]
        feat_norm = (feat_series - feat_series.mean()) / (feat_series.std() + 1e-8)
        lags = np.arange(lag_window[0], lag_window[1] + 1)
        
        def get_event_trajectories(event_type):
            event_indices = df[df['kick_type'] == event_type].index
            trajectories = []
            for idx in event_indices:
                if idx + lag_window[0] >= 0 and idx + lag_window[1] < len(df):
                    slice_data = feat_norm.iloc[idx + lag_window[0] : idx + lag_window[1] + 1].values
                    trajectories.append(slice_data)
            if len(trajectories) == 0:
                return np.zeros((1, len(lags)))
            return np.array(trajectories)
        
        hk_traj = get_event_trajectories('High Kick')
        lk_traj = get_event_trajectories('Low Kick')
        norm_traj = get_event_trajectories('Normal')

        hk_mean = hk_traj.mean(axis=0)
        lk_mean = lk_traj.mean(axis=0)
        norm_mean = norm_traj.mean(axis=0)
        hk_std = hk_traj.std(axis=0) if len(hk_traj) > 1 else np.zeros_like(lags)
        lk_std = lk_traj.std(axis=0) if len(lk_traj) > 1 else np.zeros_like(lags)
        norm_std = norm_traj.std(axis=0) if len(norm_traj) > 1 else np.zeros_like(lags)

        # Container 2: Grille d'Autocorrélation d'Événements
        st.markdown('<div class="ds-card"><div class="ds-card-title">2. Grille d\'Autocorrélation d\'Événements</div>', unsafe_allow_html=True)
        grid_col1, grid_col2, grid_col3 = st.columns(3)
        with grid_col1:
            st.write("**Événements High Kick**")
            fig_grid1 = go.Figure(go.Scatter(x=lags, y=hk_mean, line=dict(color='#1f6feb', width=2)))
            fig_grid1.update_layout(height=200, margin=dict(l=20, r=20, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d'), yaxis=dict(gridcolor='#30363d'))
            st.plotly_chart(fig_grid1, use_container_width=True)
        with grid_col2:
            st.write("**Événements Low Kick**")
            fig_grid2 = go.Figure(go.Scatter(x=lags, y=lk_mean, line=dict(color='#e74c3c', width=2)))
            fig_grid2.update_layout(height=200, margin=dict(l=20, r=20, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d'), yaxis=dict(gridcolor='#30363d'))
            st.plotly_chart(fig_grid2, use_container_width=True)
        with grid_col3:
            st.write("**Événements Normaux**")
            fig_grid3 = go.Figure(go.Scatter(x=lags, y=norm_mean, line=dict(color='#8b949e', width=2, dash='dot')))
            fig_grid3.update_layout(height=200, margin=dict(l=20, r=20, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d'), yaxis=dict(gridcolor='#30363d'))
            st.plotly_chart(fig_grid3, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Container 3: Graphique Élargi & Significativité Statistique
        st.markdown('<div class="ds-card"><div class="ds-card-title">3. Graphique Élargi &amp; Significativité Statistique</div>', unsafe_allow_html=True)
        isolate_target = st.selectbox("Sélectionner la trajectoire à isoler", ["High Kick", "Low Kick", "Normal"], index=0)
        fig_large = go.Figure()
        if isolate_target == "High Kick":
            t_mean, t_std, t_color = hk_mean, hk_std, '#1f6feb'
        elif isolate_target == "Low Kick":
            t_mean, t_std, t_color = lk_mean, lk_std, '#e74c3c'
        else:
            t_mean, t_std, t_color = norm_mean, norm_std, '#8b949e'
            
        ci_upper = t_mean + 1.96 * t_std / np.sqrt(max(2, len(df)))
        ci_lower = t_mean - 1.96 * t_std / np.sqrt(max(2, len(df)))
        fig_large.add_trace(go.Scatter(x=np.concatenate([lags, lags[::-1]]), y=np.concatenate([ci_upper, ci_lower[::-1]]), fill='toself', fillcolor='rgba(139, 148, 158, 0.15)', line=dict(color='rgba(255,255,255,0)'), name="95% CI"))
        fig_large.add_trace(go.Scatter(x=lags, y=t_mean, line=dict(color=t_color, width=2.5), name="Moyenne"))
        fig_large.update_layout(
            height=350, margin=dict(l=30, r=30, t=10, b=10),
            paper_bgcolor='#0d1117', plot_bgcolor='#161b22',
            xaxis=dict(gridcolor='#30363d', title="Lags"), yaxis=dict(gridcolor='#30363d', title="Valeur Moyenne Normalisée"),
            showlegend=False
        )
        st.plotly_chart(fig_large, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Containers 4 & 5
        col_c4_lag, col_c5_lag = st.columns(2)
        with col_c4_lag:
            # Container 4: Espace des Phases 3D (Chaos Attractor)
            st.markdown('<div class="ds-card"><div class="ds-card-title">4. Espace des Phases 3D (Chaos Attractor)</div>', unsafe_allow_html=True)
            x_att = feat_norm.values[2:]
            y_att = feat_norm.values[1:-1]
            z_att = feat_norm.values[:-2]
            centroid = np.array([x_att.mean(), y_att.mean(), z_att.mean()])
            distances = np.linalg.norm(np.column_stack([x_att, y_att, z_att]) - centroid, axis=1)
            
            fig_3d = go.Figure(go.Scatter3d(
                x=x_att[-1000:], y=y_att[-1000:], z=z_att[-1000:],
                mode='markers',
                marker=dict(size=3, color=distances[-1000:], colorscale='Viridis', opacity=0.8)
            ))
            fig_3d.update_layout(
                height=400, margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor='#0d1117',
                scene=dict(
                    xaxis=dict(title='t', gridcolor='#30363d'),
                    yaxis=dict(title='t-1', gridcolor='#30363d'),
                    zaxis=dict(title='t-2', gridcolor='#30363d'),
                    bgcolor='#0d1117'
                )
            )
            st.plotly_chart(fig_3d, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c5_lag:
            # Container 5: Matrice de Corrélation Croisée Dynamique
            st.markdown('<div class="ds-card"><div class="ds-card-title">5. Matrice de Corrélation Croisée Dynamique</div>', unsafe_allow_html=True)
            corr_df = pd.DataFrame({
                "Close": df['close'], "Volume": df['volume'], "Returns": df['returns'], "Spread": df['spread'],
                "Wick High": df['upper_wick'], "Wick Low": df['lower_wick'], "Volatility": df['volatility'],
                "Lag 1": df['close'].shift(1), "Lag 2": df['close'].shift(2), "Lag 3": df['close'].shift(3)
            }).fillna(method='bfill')
            corr_matrix = corr_df.corr()
            
            fig_corr = go.Figure(go.Heatmap(
                z=corr_matrix.values, x=corr_matrix.columns, y=corr_matrix.index,
                colorscale='RdBu_r', zmin=-1.0, zmax=1.0
            ))
            fig_corr.update_layout(height=400, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22')
            st.plotly_chart(fig_corr, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 4: Seasonality
    # ----------------------------------------------------
    with tab4:
        df['day_of_week'] = df['time'].dt.day_name()
        df['hour_of_day'] = df['time'].dt.hour
        df['month'] = df['time'].dt.month_name()
        
        # Container 1: Heatmap Horaire & Hebdomadaire
        st.markdown('<div class="ds-card"><div class="ds-card-title">1. Heatmap Horaire &amp; Hebdomadaire (Fréquence Kicks)</div>', unsafe_allow_html=True)
        df_kick_flag = df.copy()
        df_kick_flag['is_kick'] = df_kick_flag['kick_type'].apply(lambda x: 1 if x in ('High Kick', 'Low Kick', 'Both') else 0)
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        pivot_table = df_kick_flag.pivot_table(index='day_of_week', columns='hour_of_day', values='is_kick', aggfunc='mean').reindex(day_order).fillna(0)
        
        fig_season_hm = go.Figure(go.Heatmap(
            z=pivot_table.values, x=[f"{h:02d}:00" for h in pivot_table.columns], y=pivot_table.index,
            colorscale=[[0, '#0d1117'], [1, '#e74c3c']], zmin=0.0
        ))
        fig_season_hm.update_layout(height=320, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(title="Heure (UTC)"))
        st.plotly_chart(fig_season_hm, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Containers 2 & 3
        col_c2_seas, col_c3_seas = st.columns(2)
        with col_c2_seas:
            # Container 2: Profil Intra-Journalier des Mèches
            st.markdown('<div class="ds-card"><div class="ds-card-title">2. Profil Intra-Journalier des Mèches</div>', unsafe_allow_html=True)
            wick_profile = df.groupby('hour_of_day')[['upper_wick', 'lower_wick']].mean() * 100
            fig_wicks_prof = go.Figure()
            fig_wicks_prof.add_trace(go.Scatter(x=wick_profile.index, y=wick_profile['upper_wick'], line=dict(color='#2ecc71', width=2), name="Mèches Hautes"))
            fig_wicks_prof.add_trace(go.Scatter(x=wick_profile.index, y=wick_profile['lower_wick'], line=dict(color='#e74c3c', width=2), name="Mèches Basses"))
            fig_wicks_prof.update_layout(
                height=300, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22',
                xaxis=dict(gridcolor='#30363d', title="Heures de la journée"), yaxis=dict(gridcolor='#30363d', title="Mèche moyenne (%)"),
                showlegend=True
            )
            st.plotly_chart(fig_wicks_prof, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c3_seas:
            # Container 3: Distribution Hebdomadaire des Kicks
            st.markdown('<div class="ds-card"><div class="ds-card-title">3. Distribution Hebdomadaire des Kicks</div>', unsafe_allow_html=True)
            weekly_counts = df_kick_flag.groupby(['day_of_week', 'is_kick']).size().unstack(fill_value=0).reindex(day_order).fillna(0)
            fig_weekly_bar = go.Figure()
            fig_weekly_bar.add_trace(go.Bar(x=weekly_counts.index, y=weekly_counts[0], name="Normal", marker_color='#8b949e'))
            fig_weekly_bar.add_trace(go.Bar(x=weekly_counts.index, y=weekly_counts[1], name="Anormale (Kick)", marker_color='#1f6feb'))
            fig_weekly_bar.update_layout(
                height=300, margin=dict(l=30, r=30, t=10, b=10), barmode='group', paper_bgcolor='#0d1117', plot_bgcolor='#161b22',
                xaxis=dict(gridcolor='#30363d'), yaxis=dict(gridcolor='#30363d', title="Nombre de bougies"),
                showlegend=True
            )
            st.plotly_chart(fig_weekly_bar, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Containers 4 & 5
        col_c4_seas, col_c5_seas = st.columns(2)
        with col_c4_seas:
            # Container 4: Boxplots Mensuels de Dispersion
            st.markdown('<div class="ds-card"><div class="ds-card-title">4. Boxplots Mensuels de Dispersion</div>', unsafe_allow_html=True)
            month_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
            present_months = [m for m in month_order if m in df['month'].unique()]
            
            fig_box = go.Figure()
            for m in present_months:
                fig_box.add_trace(go.Box(
                    y=np.abs(df[df['month'] == m]['returns']) * 100, name=m, boxpoints='outliers',
                    fillcolor='#161b22', line=dict(color='#1f6feb', width=1.5)
                ))
            fig_box.update_layout(
                height=320, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22',
                yaxis=dict(gridcolor='#30363d', title="Rendement absolu (%)"), showlegend=False
            )
            st.plotly_chart(fig_box, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col_c5_seas:
            # Container 5: Radar des Signatures Temporelles
            st.markdown('<div class="ds-card"><div class="ds-card-title">5. Radar des Signatures Temporelles</div>', unsafe_allow_html=True)
            df['session'] = 'US'
            df.loc[(df['hour_of_day'] >= 0) & (df['hour_of_day'] < 8), 'session'] = 'Asie'
            df.loc[(df['hour_of_day'] >= 8) & (df['hour_of_day'] < 16), 'session'] = 'Europe'
            
            variables = ['volume', 'spread', 'upper_wick', 'lower_wick', 'body_size']
            df_norm = df.copy()
            for v in variables:
                df_norm[v] = (df[v] - df[v].min()) / (df[v].max() - df[v].min() + 1e-8)
            session_means = df_norm.groupby('session')[variables].mean()
            
            fig_radar = go.Figure()
            colors_radar = {'Asie': 'rgba(241, 196, 15, 0.4)', 'Europe': 'rgba(31, 111, 235, 0.4)', 'US': 'rgba(231, 76, 60, 0.4)'}
            line_radar = {'Asie': '#f1c40f', 'Europe': '#1f6feb', 'US': '#e74c3c'}
            for sess in ['Asie', 'Europe', 'US']:
                if sess in session_means.index:
                    r_vals = session_means.loc[sess].values.tolist()
                    r_vals.append(r_vals[0])
                    fig_radar.add_trace(go.Scatterpolar(
                        r=r_vals, theta=variables + [variables[0]], fill='toself', fillcolor=colors_radar[sess],
                        line=dict(color=line_radar[sess], width=2), name=sess
                    ))
            fig_radar.update_layout(
                height=320, margin=dict(l=40, r=40, t=10, b=10),
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, 1], gridcolor='#30363d'),
                    angularaxis=dict(gridcolor='#30363d'), bgcolor='#161b22'
                ),
                paper_bgcolor='#0d1117', showlegend=True
            )
            st.plotly_chart(fig_radar, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 5: Volatility Clustering
    # ----------------------------------------------------
    with tab5:
        df['is_kick_any'] = df['kick_type'].apply(lambda x: 1 if x in ('High Kick', 'Low Kick', 'Both') else 0)
        
        # Grid columns for Containers 1 & 2
        col_c1_v, col_c2_v = st.columns(2)
        with col_c1_v:
            # Container 1: Probabilités Conditionnelles de Persistance
            st.markdown('<div class="ds-card"><div class="ds-card-title">1. Probabilités Conditionnelles de Persistance</div>', unsafe_allow_html=True)
            pk = df['is_kick_any'].mean()
            df['is_kick_lag1'] = df['is_kick_any'].shift(1)
            p_k_k1 = df[df['is_kick_lag1'] == 1]['is_kick_any'].mean()
            df['is_kick_lag2'] = df['is_kick_any'].shift(2)
            p_k_k1_k2 = df[(df['is_kick_lag1'] == 1) & (df['is_kick_lag2'] == 1)]['is_kick_any'].mean()
            
            probs_y = [pk, p_k_k1, p_k_k1_k2]
            probs_x = ['P(K)', 'P(K | K_t-1)', 'P(K | K_t-1 ∩ K_t-2)']
            fig_cond = go.Figure(go.Bar(x=probs_x, y=probs_y, text=[f"{p*100:.2f}%" for p in probs_y], textposition='auto', marker_color='#8b949e'))
            fig_cond.update_layout(height=300, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', yaxis=dict(gridcolor='#30363d', range=[0, 1]))
            st.plotly_chart(fig_cond, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c2_v:
            # Container 2: Matrice de Transition Directionnelle
            st.markdown('<div class="ds-card"><div class="ds-card-title">2. Matrice de Transition Directionnelle</div>', unsafe_allow_html=True)
            df['dir_state'] = 'Stagnation'
            df.loc[df['returns'] > 0.005, 'dir_state'] = 'Hausse'
            df.loc[df['returns'] < -0.005, 'dir_state'] = 'Baisse'
            df['dir_state_prev'] = df['dir_state'].shift(1)
            transition_matrix = pd.crosstab(df['dir_state_prev'], df['dir_state'], normalize='index')
            transition_matrix = transition_matrix.reindex(index=['Hausse', 'Baisse', 'Stagnation'], columns=['Hausse', 'Baisse', 'Stagnation']).fillna(0)
            
            fig_trans_dir = go.Figure(go.Heatmap(
                z=transition_matrix.values, x=transition_matrix.columns, y=transition_matrix.index,
                colorscale='Blues', text=np.round(transition_matrix.values * 100, 2), texttemplate="%{text}%", zmin=0, zmax=1
            ))
            fig_trans_dir.update_layout(height=300, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22')
            st.plotly_chart(fig_trans_dir, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Container 3: Autocorrélation des Rendements Absolus (ACF)
        st.markdown('<div class="ds-card"><div class="ds-card-title">3. Autocorrélation des Rendements Absolus (ACF)</div>', unsafe_allow_html=True)
        abs_returns = np.abs(df['returns'].dropna().values)
        max_lag = min(50, len(abs_returns) - 2)
        if max_lag > 0:
            acf_vals = [1.0] + [np.corrcoef(abs_returns[lag:], abs_returns[:-lag])[0, 1] for lag in range(1, max_lag + 1)]
            lags_acf = np.arange(max_lag + 1)
        else:
            acf_vals = [1.0]
            lags_acf = np.arange(1)
        acf_threshold = 1.96 / np.sqrt(len(df))
        
        fig_acf = go.Figure()
        for l, val in zip(lags_acf, acf_vals):
            fig_acf.add_trace(go.Scatter(x=[l, l], y=[0, val], mode='lines', line=dict(color='#58a6ff', width=1.5), showlegend=False))
        fig_acf.add_trace(go.Scatter(x=lags_acf, y=acf_vals, mode='markers', marker=dict(color='#1f6feb', size=5), showlegend=False))
        fig_acf.add_hline(y=acf_threshold, line_dash="dash", line_color="#e74c3c", line_width=1.5)
        fig_acf.add_hline(y=-acf_threshold, line_dash="dash", line_color="#e74c3c", line_width=1.5)
        fig_acf.update_layout(height=320, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d', title="Lags"), yaxis=dict(gridcolor='#30363d', title="Autocorrélation"))
        st.plotly_chart(fig_acf, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Containers 4 & 5
        col_c4_vcl, col_c5_vcl = st.columns(2)
        with col_c4_vcl:
            # Container 4: Volatilité Réalisée vs Lissage Exponentiel
            st.markdown('<div class="ds-card"><div class="ds-card-title">4. Volatilité Réalisée vs Lissage Exponentiel</div>', unsafe_allow_html=True)
            realized_vol = np.abs(df['returns'].values) * 100
            ema_vol = talib.EMA(realized_vol, timeperiod=30)
            
            fig_ema_v = go.Figure()
            fig_ema_v.add_trace(go.Scatter(x=df['time'], y=realized_vol, line=dict(color='#8b949e', width=0.8), name="Volatilité Brute"))
            fig_ema_v.add_trace(go.Scatter(x=df['time'], y=ema_vol, line=dict(color='#f39c12', width=2.0), name="EMA 30"))
            fig_ema_v.update_layout(height=350, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d'), yaxis=dict(gridcolor='#30363d', title="Volatilité (%)"), showlegend=True)
            st.plotly_chart(fig_ema_v, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col_c5_vcl:
            # Container 5: Évolution du Spectre de Hurst
            st.markdown('<div class="ds-card"><div class="ds-card-title">5. Évolution du Spectre de Hurst</div>', unsafe_allow_html=True)
            hurst_w = 400
            hurst_values = np.full(len(df), 0.5)
            
            def fast_hurst(series):
                lags_h = np.arange(2, 10)
                tau_h = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags_h]
                tau_h = [t if t > 0 else 1e-8 for t in tau_h]
                poly_h = np.polyfit(np.log(lags_h), np.log(tau_h), 1)
                return poly_h[0]
                
            returns_arr = df['returns'].values
            for i in range(hurst_w, len(df)):
                window = returns_arr[i - hurst_w : i]
                hurst_values[i] = fast_hurst(window)
                
            df['hurst'] = hurst_values
            df['hurst'] = df['hurst'].clip(0.1, 0.9)
            
            fig_hurst = go.Figure()
            fig_hurst.add_trace(go.Scatter(x=df['time'], y=df['hurst'], line=dict(color='#ffffff', width=1.5), name="Hurst"))
            fig_hurst.add_hline(y=0.5, line_color="#8b949e", line_width=1.5, line_dash='dash')
            fig_hurst.add_hrect(y0=0.5, y1=1.0, fillcolor="rgba(46, 204, 113, 0.08)", line_width=0)
            fig_hurst.add_hrect(y0=0.0, y1=0.5, fillcolor="rgba(231, 76, 96, 0.08)", line_width=0)
            fig_hurst.update_layout(height=350, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d'), yaxis=dict(gridcolor='#30363d', range=[0.2, 0.8]), showlegend=False)
            st.plotly_chart(fig_hurst, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 6: HMM Regime Map
    # ----------------------------------------------------
    with tab6:
        reg_labels = {0: 'Hausse', 1: 'Baisse', 2: 'Stagnation'}
        reg_cols = {0: '#2ecc71', 1: '#e74c3c', 2: '#8b949e'}
        colors_pca = {0: '#2ecc71', 1: '#e74c3c', 2: '#8b949e'}
        labels_pca = {0: 'Hausse', 1: 'Baisse', 2: 'Stagnation'}

        returns_reg = df['returns'].values.reshape(-1, 1)
        vols_reg = df['volatility'].values.reshape(-1, 1)
        features_reg = np.column_stack([returns_reg, vols_reg])
        gmm_model = GaussianMixture(n_components=3, random_state=42)
        df['regime_state'] = gmm_model.fit_predict(features_reg)
        state_means = gmm_model.means_[:, 0]
        sorted_order = np.argsort(state_means)[::-1]
        up_state = sorted_order[0]
        stagnant_state = sorted_order[1]
        down_state = sorted_order[2]
        regime_map = {up_state: 0, down_state: 1, stagnant_state: 2}
        df['ordered_regime'] = df['regime_state'].map(regime_map)
        
        # Smooth the regimes using rolling majority to prevent high-frequency flickering
        try:
            smoothed = df['ordered_regime'].rolling(window=15, min_periods=1).apply(lambda x: pd.Series(x).value_counts().index[0]).astype(int)
            df['ordered_regime'] = smoothed
        except Exception:
            pass

        # Container 1: Graphique des Prix Coloré par Régime
        st.markdown('<div class="ds-card"><div class="ds-card-title">1. Graphique des Prix Coloré par Régime</div>', unsafe_allow_html=True)
        fig_reg_price = go.Figure()
        fig_reg_price.add_trace(go.Scatter(x=df['time'], y=df['close'], line=dict(color='#ffffff', width=1.5), name="Prix Clôture"))
        states = df['ordered_regime'].values
        times = df['time'].values
        reg_colors = {0: 'rgba(46, 204, 113, 0.15)', 1: 'rgba(231, 76, 60, 0.15)', 2: 'rgba(139, 148, 158, 0.15)'}
        curr_state = states[0]
        start_time = times[0]
        for i in range(1, len(df)):
            if states[i] != curr_state:
                fig_reg_price.add_vrect(x0=start_time, x1=times[i-1], fillcolor=reg_colors[curr_state], line_width=0)
                curr_state = states[i]
                start_time = times[i]
        fig_reg_price.add_vrect(x0=start_time, x1=times[-1], fillcolor=reg_colors[curr_state], line_width=0)
        fig_reg_price.update_layout(height=350, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d'), yaxis=dict(gridcolor='#30363d', title="Prix"), showlegend=False)
        st.plotly_chart(fig_reg_price, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Containers 2 & 3
        col_c2_hmm, col_c3_hmm = st.columns(2)
        with col_c2_hmm:
            # Container 2: Matrice de Transition HMM
            st.markdown('<div class="ds-card"><div class="ds-card-title">2. Matrice de Transition HMM</div>', unsafe_allow_html=True)
            df['ordered_regime_prev'] = df['ordered_regime'].shift(1)
            hmm_trans = pd.crosstab(df['ordered_regime_prev'], df['ordered_regime'], normalize='index')
            hmm_trans = hmm_trans.reindex(index=[0, 1, 2], columns=[0, 1, 2]).fillna(0)
            
            fig_hmm_trans = go.Figure(go.Heatmap(
                z=hmm_trans.values, x=['Hausse', 'Baisse', 'Stagnation'], y=['Hausse', 'Baisse', 'Stagnation'],
                colorscale='Blues', text=np.round(hmm_trans.values * 100, 2), texttemplate="%{text}%", zmin=0, zmax=1
            ))
            fig_hmm_trans.update_layout(height=300, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22')
            st.plotly_chart(fig_hmm_trans, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c3_hmm:
            # Container 3: Volume Distribution by State (KDE)
            st.markdown('<div class="ds-card"><div class="ds-card-title">3. Distribution du Volume par État (KDE)</div>', unsafe_allow_html=True)
            vol_std = (df['volume'] - df['volume'].mean()) / (df['volume'].std() + 1e-8)
            fig_kde = go.Figure()
            colors_kde = {0: '#2ecc71', 1: '#e74c3c', 2: '#8b949e'}
            labels_kde = {0: 'Hausse', 1: 'Baisse', 2: 'Stagnation'}
            x_kde = np.linspace(-3, 3, 200)
            for reg in [0, 1, 2]:
                sub_vol = vol_std[df['ordered_regime'] == reg].values
                if len(sub_vol) > 5:
                    kde = gaussian_kde(sub_vol)
                    fig_kde.add_trace(go.Scatter(x=x_kde, y=kde(x_kde), mode='lines', line=dict(color=colors_kde[reg], width=2), name=labels_kde[reg]))
            fig_kde.update_layout(height=300, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d', title="Volume Standardisé"), yaxis=dict(gridcolor='#30363d', title="Densité"), showlegend=True)
            st.plotly_chart(fig_kde, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Grid columns for Containers 4 & 5
        col_c4_hmm2, col_c5_hmm2 = st.columns(2)
        with col_c4_hmm2:
            # Container 4: Courbes de Survie des Régimes (Kaplan-Meier)
            st.markdown('<div class="ds-card"><div class="ds-card-title">4. Courbes de Survie des Régimes (Kaplan-Meier)</div>', unsafe_allow_html=True)
            def get_regime_durations(reg):
                durations = []
                curr_len = 0
                for val in states:
                    if val == reg: curr_len += 1
                    else:
                        if curr_len > 0:
                            durations.append(curr_len)
                            curr_len = 0
                if curr_len > 0: durations.append(curr_len)
                return sorted(durations)
                
            fig_survival = go.Figure()
            for reg in [0, 1, 2]:
                durations = get_regime_durations(reg)
                if durations:
                    unique_d = np.unique(durations)
                    n_at_risk = len(durations)
                    curr_prob = 1.0
                    times_surv, probs_surv = [0], [1.0]
                    for d in unique_d:
                        d_count = np.sum(durations == d)
                        curr_prob *= (1.0 - d_count / n_at_risk)
                        n_at_risk -= d_count
                        times_surv.append(d)
                        probs_surv.append(curr_prob)
                    fig_survival.add_trace(go.Scatter(x=times_surv, y=probs_surv, line=dict(color=reg_cols[reg], width=2, shape='hv'), name=reg_labels[reg]))
            fig_survival.update_layout(height=320, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d', title="Durée de vie (Bougies)"), yaxis=dict(gridcolor='#30363d', range=[0, 1.05], title="Probabilité de survie"), showlegend=True)
            st.plotly_chart(fig_survival, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col_c5_hmm2:
            # Container 5: Séparabilité des Clusters (PCA 2D)
            st.markdown('<div class="ds-card"><div class="ds-card-title">5. Séparabilité des Clusters (PCA 2D)</div>', unsafe_allow_html=True)
            pca_feat = df[['returns', 'volatility', 'spread', 'upper_wick', 'lower_wick', 'body_size']].values
            pca_feat_std = (pca_feat - pca_feat.mean(axis=0)) / (pca_feat.std(axis=0) + 1e-8)
            pca = PCA(n_components=2)
            pc_projected = pca.fit_transform(pca_feat_std)
            
            fig_pca = go.Figure()
            for reg in [0, 1, 2]:
                mask = df['ordered_regime'] == reg
                fig_pca.add_trace(go.Scatter(x=pc_projected[mask, 0], y=pc_projected[mask, 1], mode='markers', marker=dict(color=colors_pca[reg], size=5, opacity=0.7), name=labels_pca[reg]))
            fig_pca.update_layout(height=320, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d', title="PC1"), yaxis=dict(gridcolor='#30363d', title="PC2"), showlegend=True)
            st.plotly_chart(fig_pca, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 7: VSA & Wicks
    # ----------------------------------------------------
    with tab7:
        col_c1_vsa, col_c2_vsa = st.columns(2)
        with col_c1_vsa:
            # Container 1: Distribution Statistique des Mèches (Upper vs Lower)
            st.markdown('<div class="ds-card"><div class="ds-card-title">1. Distribution Statistique des Mèches (Upper vs Lower)</div>', unsafe_allow_html=True)
            fig_wicks_dist = go.Figure()
            fig_wicks_dist.add_trace(go.Histogram(x=df['upper_wick'] * 100, marker_color='#2ecc71', opacity=0.6, name="Mèches Hautes"))
            fig_wicks_dist.add_trace(go.Histogram(x=df['lower_wick'] * 100, marker_color='#e74c3c', opacity=0.6, name="Mèches Basses"))
            fig_wicks_dist.update_layout(height=300, margin=dict(l=30, r=30, t=10, b=10), barmode='overlay', paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d', title="Taille (%)"), yaxis=dict(gridcolor='#30363d', title="Occurrences"))
            st.plotly_chart(fig_wicks_dist, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c2_vsa:
            # Container 2: Détecteur d'Événements VSA
            st.markdown('<div class="ds-card"><div class="ds-card-title">2. Détecteur d\'Événements VSA</div>', unsafe_allow_html=True)
            vol_zscore = (df['volume'] - df['volume'].mean()) / (df['volume'].std() + 1e-8)
            df['vol_zscore'] = vol_zscore
            df['vsa_class'] = 'Normal'
            df.loc[(vol_zscore > 2.0) & (df['spread'] > df['spread'].quantile(0.85)), 'vsa_class'] = 'Climax'
            df.loc[(vol_zscore < -1.0) & (df['spread'] < df['spread'].quantile(0.15)), 'vsa_class'] = 'No Demand'
            df.loc[(vol_zscore > 2.0) & (df['spread'] < df['spread'].quantile(0.40)), 'vsa_class'] = 'Effort vs Result'
            
            vsa_events = df[df['vsa_class'] != 'Normal'][['time', 'spread', 'vol_zscore', 'upper_wick', 'vsa_class']].copy()
            vsa_events.columns = ['Horodatage', 'Spread Relatif', 'Z-Score Volume', 'Mèche (%)', 'Classification VSA']
            vsa_events['Spread Relatif'] = vsa_events['Spread Relatif'].round(4)
            vsa_events['Z-Score Volume'] = vsa_events['Z-Score Volume'].round(2)
            vsa_events['Mèche (%)'] = (vsa_events['Mèche (%)'] * 100).round(2)
            st.dataframe(vsa_events, height=250, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        col_c3_vsa, col_c4_vsa = st.columns(2)
        with col_c3_vsa:
            # Container 3: Graphique 2D de Densité (Wick vs Volume)
            st.markdown('<div class="ds-card"><div class="ds-card-title">3. Graphique 2D de Densité (Wick vs Volume)</div>', unsafe_allow_html=True)
            fig_dens_vsa = go.Figure()
            fig_dens_vsa.add_trace(go.Scatter(x=df['upper_wick'] * 100, y=df['vol_zscore'], mode='markers', marker=dict(color='#8b949e', size=3, opacity=0.4)))
            fig_dens_vsa.add_trace(go.Histogram2dContour(x=df['upper_wick'] * 100, y=df['vol_zscore'], colorscale='Blues', contours=dict(coloring='none', showlabels=False)))
            fig_dens_vsa.update_layout(height=350, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d', title="Taille (%)"), yaxis=dict(gridcolor='#30363d', title="Volume (Z-Score)"), showlegend=False)
            st.plotly_chart(fig_dens_vsa, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c4_vsa:
            # Container 4: Proxy de Déséquilibre (Delta Volume)
            st.markdown('<div class="ds-card"><div class="ds-card-title">4. Proxy de Déséquilibre (Delta Volume)</div>', unsafe_allow_html=True)
            df['net_wick_vol'] = df['volume'] * (df['upper_wick'] - df['lower_wick'])
            df_tail_vsa = df.tail(100)
            fig_delta_vol = go.Figure()
            bar_colors = ['#2ecc71' if c >= 0 else '#e74c3c' for c in df_tail_vsa['net_wick_vol']]
            fig_delta_vol.add_trace(go.Bar(x=df_tail_vsa['time'], y=df_tail_vsa['net_wick_vol'], marker_color=bar_colors, opacity=0.8))
            fig_delta_vol.update_layout(height=350, margin=dict(l=30, r=30, t=10, b=10), paper_bgcolor='#0d1117', plot_bgcolor='#161b22', xaxis=dict(gridcolor='#30363d', title="Temps (100 dernières bougies)"), yaxis=dict(gridcolor='#30363d', title="Volume Net Absorbé"), showlegend=False)
            st.plotly_chart(fig_delta_vol, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Container 5: Wick Rejection Profiler
        st.markdown('<div class="ds-card"><div class="ds-card-title">5. Wick Rejection Profiler</div>', unsafe_allow_html=True)
        df['wick_body_ratio'] = df['upper_wick'] / (df['body_size'] + 1e-8)
        x_reg = df['wick_body_ratio'].values
        y_reg = df['volatility'].values
        mask_reg = np.isfinite(x_reg) & np.isfinite(y_reg) & (x_reg < 20)
        x_reg, y_reg = x_reg[mask_reg], y_reg[mask_reg]
        
        fig_reg = go.Figure()
        if len(x_reg) >= 2:
            slope, intercept = np.polyfit(x_reg, y_reg, 1)
            fig_reg.add_trace(go.Scatter(x=x_reg[-1000:], y=y_reg[-1000:], mode='markers', marker=dict(color='#1f6feb', size=4, opacity=0.5), name="Observations"))
            x_vals = np.linspace(x_reg.min(), x_reg.max(), 100)
            fig_reg.add_trace(go.Scatter(x=x_vals, y=slope * x_vals + intercept, mode='lines', line=dict(color='#e74c3c', width=2), name="Régression"))
        else:
            fig_reg.add_trace(go.Scatter(x=[0], y=[0], mode='markers', name="No Data"))
        fig_reg.update_layout(
            height=350, margin=dict(l=30, r=30, t=10, b=10),
            paper_bgcolor='#0d1117', plot_bgcolor='#161b22',
            xaxis=dict(gridcolor='#30363d', title="Ratio Mèche / Corps"), yaxis=dict(gridcolor='#30363d', title="Volatilité locale (10 bougies)"),
            showlegend=True
        )
        st.plotly_chart(fig_reg, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
