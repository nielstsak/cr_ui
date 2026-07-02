import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from sklearn.decomposition import PCA

def compute_base_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule les features de base (rendements, volatilité, spread, mèches)
    à partir d'un DataFrame OHLCV.
    """
    df = df.copy()
    
    df['returns'] = df['close'].pct_change()
    
    df['volatility'] = df['returns'].rolling(window=10).std()
    
    df['spread'] = (df['high'] - df['low']) / df['close']
    
    df['upper_wick'] = (df['high'] - np.maximum(df['open'], df['close'])) / df['close']
    
    df['lower_wick'] = (np.minimum(df['open'], df['close']) - df['low']) / df['close']
    
    df['body_size'] = np.abs(df['close'] - df['open']) / df['close']
    
    df.fillna(method='bfill', inplace=True)
    
    return df

def detect_kicks(df: pd.DataFrame, kick_threshold_pct: float) -> pd.DataFrame:
    """
    Identifie les Kicks (High, Low, Both, Normal) basés sur un seuil de rendement.
    Prépare également les flags de persistance pour l'analyse de volatilité.
    """
    df = df.copy()
    
    kick_pct = kick_threshold_pct / 100.0
    df['kick_type'] = 'Normal'
    df.loc[df['returns'] >= kick_pct, 'kick_type'] = 'High Kick'
    df.loc[df['returns'] <= -kick_pct, 'kick_type'] = 'Low Kick'

    prev_kick = df['kick_type'].shift(1)
    curr_kick = df['kick_type']
    
    mask_both = (
        (prev_kick.isin(['High Kick', 'Low Kick'])) & 
        (curr_kick.isin(['High Kick', 'Low Kick'])) & 
        (prev_kick != curr_kick)
    )
    df.loc[mask_both, 'kick_type'] = 'Both'
    
    df['is_kick_any'] = df['kick_type'].apply(lambda x: 1 if x in ('High Kick', 'Low Kick', 'Both') else 0)
    
    return df

def compute_directional_transitions(df: pd.DataFrame) -> dict:
    """
    Calcule la matrice de transition directionnelle.
    Retourne un dictionnaire sérialisable pour l'API.
    """
    df = df.copy()
    df['dir_state'] = 'Stagnation'
    df.loc[df['returns'] > 0.005, 'dir_state'] = 'Hausse'
    df.loc[df['returns'] < -0.005, 'dir_state'] = 'Baisse'
    df['dir_state_prev'] = df['dir_state'].shift(1)
    
    transition_matrix = pd.crosstab(df['dir_state_prev'], df['dir_state'], normalize='index')
    transition_matrix = transition_matrix.reindex(
        index=['Hausse', 'Baisse', 'Stagnation'], 
        columns=['Hausse', 'Baisse', 'Stagnation']
    ).fillna(0)
    
    return transition_matrix.to_dict(orient="index")

def compute_conditional_probabilities(df: pd.DataFrame) -> dict:
    """
    Calcule les probabilités conditionnelles de clustering de volatilité:
    P(K), P(K|K_t-1), P(K|K_t-1, K_t-2).
    """
    if 'is_kick_any' not in df.columns:
        return {"p_k": 0.0, "p_k_k1": 0.0, "p_k_k1_k2": 0.0}
        
    pk = df['is_kick_any'].mean()
    
    df['is_kick_lag1'] = df['is_kick_any'].shift(1)
    mask_k1 = df['is_kick_lag1'] == 1
    p_k_k1 = df[mask_k1]['is_kick_any'].mean() if mask_k1.any() else 0.0
    
    df['is_kick_lag2'] = df['is_kick_any'].shift(2)
    mask_k2 = (df['is_kick_lag1'] == 1) & (df['is_kick_lag2'] == 1)
    p_k_k1_k2 = df[mask_k2]['is_kick_any'].mean() if mask_k2.any() else 0.0
    
    return {
        "p_k": 0.0 if pd.isna(pk) else float(pk),
        "p_k_k1": 0.0 if pd.isna(p_k_k1) else float(p_k_k1),
        "p_k_k1_k2": 0.0 if pd.isna(p_k_k1_k2) else float(p_k_k1_k2)
    }

def compute_hmm_regimes(df: pd.DataFrame, random_state: int = 42) -> pd.DataFrame:
    """
    Entraîne un modèle de mélange Gaussien (GMM) pour identifier les 3 régimes de marché
    (Hausse, Baisse, Stagnation) et applique un lissage par vote majoritaire.
    """
    df = df.copy()
    
    mask = np.isfinite(df['returns']) & np.isfinite(df['volatility'])
    
    if not mask.any():
        df['ordered_regime'] = 2 
        return df
        
    returns_reg = df.loc[mask, 'returns'].values.reshape(-1, 1)
    vols_reg = df.loc[mask, 'volatility'].values.reshape(-1, 1)
    features_reg = np.column_stack([returns_reg, vols_reg])
    
    gmm_model = GaussianMixture(n_components=3, random_state=random_state)
    regime_states = gmm_model.fit_predict(features_reg)
    
    state_means = gmm_model.means_[:, 0]
    sorted_order = np.argsort(state_means)[::-1]
    up_state = sorted_order[0]
    stagnant_state = sorted_order[1]
    down_state = sorted_order[2]
    
    regime_map = {up_state: 0, down_state: 1, stagnant_state: 2}
    
    df['regime_state'] = np.nan
    df.loc[mask, 'regime_state'] = regime_states
    df['ordered_regime'] = df['regime_state'].map(regime_map)
    
    try:
        smoothed = df['ordered_regime'].rolling(window=15, min_periods=1).apply(
            lambda x: pd.Series(x).mode()[0] if not pd.Series(x).mode().empty else np.nan
        )
        df['ordered_regime'] = smoothed.fillna(2).astype(int)
    except Exception:
        df['ordered_regime'] = df['ordered_regime'].fillna(2).astype(int)
        
    return df

def compute_pca_clusters(df: pd.DataFrame) -> dict:
    """
    Calcule la projection PCA 2D pour visualiser la séparabilité des régimes HMM.
    Retourne un dictionnaire listant les coordonnées de chaque régime.
    """
    features = ['returns', 'volatility', 'spread', 'upper_wick', 'lower_wick', 'body_size']
    
    if 'ordered_regime' not in df.columns or not all(f in df.columns for f in features):
        return {}
        
    df_clean = df.dropna(subset=features + ['ordered_regime']).copy()
    if len(df_clean) < 3:
        return {}
        
    pca_feat = df_clean[features].values
    pca_feat_std = (pca_feat - pca_feat.mean(axis=0)) / (pca_feat.std(axis=0) + 1e-8)
    
    pca = PCA(n_components=2)
    pc_projected = pca.fit_transform(pca_feat_std)
    
    result = {0: {"pc1": [], "pc2": []}, 1: {"pc1": [], "pc2": []}, 2: {"pc1": [], "pc2": []}}
    
    regimes = df_clean['ordered_regime'].values
    for i in range(len(regimes)):
        reg = int(regimes[i])
        if reg in result:
            result[reg]["pc1"].append(float(pc_projected[i, 0]))
            result[reg]["pc2"].append(float(pc_projected[i, 1]))
            
    return result

def compute_lagged_trajectories(df: pd.DataFrame, target_feature: str = 'returns', lag_window: tuple = (-20, 5)) -> dict:
    """
    Calcule les trajectoires moyennes, écarts-types et intervalles de confiance (95%)
    autour des événements (Kicks) pour une feature donnée.
    """
    if target_feature not in df.columns or 'kick_type' not in df.columns:
        return {}
        
    feat_series = df[target_feature]
    feat_norm = (feat_series - feat_series.mean()) / (feat_series.std() + 1e-8)
    
    lags = list(range(lag_window[0], lag_window[1] + 1))
    
    def get_event_stats(event_type):
        event_indices = df[df['kick_type'] == event_type].index
        trajectories = []
        
        for idx in event_indices:
            start_idx = idx + lag_window[0]
            end_idx = idx + lag_window[1]
            
            if start_idx >= 0 and end_idx < len(df):
                slice_data = feat_norm.iloc[start_idx : end_idx + 1].values
                trajectories.append(slice_data)
                
        if len(trajectories) == 0:
            zeros = [0.0] * len(lags)
            return {"mean": zeros, "std": zeros, "ci_upper": zeros, "ci_lower": zeros, "count": 0}
            
        traj_arr = np.array(trajectories)
        mean_val = traj_arr.mean(axis=0)
        std_val = traj_arr.std(axis=0)
        
        n_samples = max(2, len(df))
        ci_margin = 1.96 * std_val / np.sqrt(n_samples)
        
        return {
            "mean": mean_val.tolist(),
            "std": std_val.tolist(),
            "ci_upper": (mean_val + ci_margin).tolist(),
            "ci_lower": (mean_val - ci_margin).tolist(),
            "count": len(trajectories)
        }
        
    return {
        "lags": lags,
        "high_kick": get_event_stats('High Kick'),
        "low_kick": get_event_stats('Low Kick'),
        "normal": get_event_stats('Normal')
    }