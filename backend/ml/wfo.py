import logging
from typing import Callable, Dict, List, Tuple

import numpy as np
import optuna

# Import required simulation module
from backend.simulation.margin_portfolio import simulate_margin_portfolio

# Setup logger
logger = logging.getLogger("WFO")


def generate_wfo_splits(
    total_len: int,
    n_splits: int,
    train_ratio: float,
    embargo: int
) -> List[Dict[str, Tuple[int, int]]]:
    """
    Generates rolling Walk-Forward splits indices with a causal embargo.
    
    Calculates non-overlapping contiguous Out-of-Sample (Test) intervals and
    sliding In-Sample (Train) intervals. The embargo strips the last 'embargo'
    indices from the training set to prevent leakage of temporal autocorrelation.
    
    Args:
        total_len: Total length of the dataset series (N).
        n_splits: Number of walk-forward segments.
        train_ratio: Ratio of train size relative to test size (e.g. 0.80).
        embargo: Number of periods to drop at the end of training.
        
    Returns:
        A list of dictionaries representing the splits:
        [
            {
                "train": (start_train, end_train),
                "test": (start_test, end_test)
            },
            ...
        ]
    """
    if n_splits <= 0:
        raise ValueError("Number of splits must be strictly positive.")
    if not (0.0 < train_ratio < 1.0):
        raise ValueError("Train ratio must be between 0.0 and 1.0 exclusive.")
        
    # Solve the system of constraints:
    # N - embargo = (train_ratio / (1 - train_ratio) + n_splits) * L_test
    # This solves the first training segment starting exactly at index 0.
    ratio_factor = train_ratio / (1.0 - train_ratio)
    divisor = ratio_factor + n_splits
    
    available_len = total_len - embargo
    if available_len <= 0:
        raise ValueError("Dataset is too short for the configured embargo size.")
        
    L_test = int(available_len // divisor)
    if L_test <= 0:
        raise ValueError("Dataset is too short to generate the requested splits and ratios.")
        
    L_train = int(L_test * ratio_factor)
    
    splits = []
    for k in range(n_splits):
        start_train = k * L_test
        end_train_raw = start_train + L_train
        
        # Apply embargo: training ends earlier
        end_train = end_train_raw - embargo
        
        start_test = end_train_raw
        end_test = start_test + L_test
        
        # Guard boundaries
        if end_test > total_len:
            end_test = total_len
            
        splits.append({
            "train": (start_train, end_train),
            "test": (start_test, end_test)
        })
        
    return splits


def optimize_segment(
    close_train: np.ndarray,
    signals_gen_func: Callable[[np.ndarray, dict], np.ndarray],
    param_space_func: Callable[[optuna.Trial], dict],
    initial_balance: float,
    mmr: float,
    leverage: float,
    n_trials: int = 50,
    annualization_factor: float = 365.25 * 1440.0
) -> dict:
    """
    Performs hyperparameter optimization on a training segment.
    Uses Optuna to maximize the J-Score and implements progressive pruning.
    
    Args:
        close_train: 1D array of In-Sample close prices.
        signals_gen_func: Function generating position signals from close and parameters.
        param_space_func: Function suggesting parameters to the Optuna trial.
        initial_balance: Starting portfolio balance.
        mmr: Maintenance Margin Requirement.
        leverage: Fixed leverage factor.
        n_trials: Number of optimization trials.
        annualization_factor: Step frequency per year.
        
    Returns:
        A dict with optimization results: {"best_params": dict, "best_value": float, "study": Study}.
    """
    # Mute optuna logs to avoid console spamming
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    
    def objective(trial: optuna.Trial) -> float:
        params = param_space_func(trial)
        n_len = len(close_train)
        
        # 3-stage temporal progressive pruning logic
        for stage in (1, 2, 3):
            sub_len = int(n_len * stage / 3)
            close_sub = close_train[:sub_len]
            
            try:
                signals_sub = signals_gen_func(close_sub, params)
            except Exception as e:
                raise optuna.TrialPruned(f"Signal generation crashed: {e}")
                
            stats = simulate_margin_portfolio(
                close=close_sub,
                signals=signals_sub,
                initial_balance=initial_balance,
                fee_rate=0.0004,
                slippage_rate=0.0005,
                mmr=mmr,
                leverage=leverage,
                annualization_factor=annualization_factor
            )
            
            score = stats['composite_score']
            
            # Report score at this stage
            trial.report(score, step=stage)
            
            # Prune trial if performance is inferior to historical medians
            if trial.should_prune():
                raise optuna.TrialPruned()
                
        return score
        
    study = optuna.create_study(
        direction="maximize",
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=1)
    )
    study.optimize(objective, n_trials=n_trials)
    
    completed_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if len(completed_trials) == 0:
        # Fallback to the trial with the highest value among all trials (including pruned ones)
        valid_trials = [t for t in study.trials if t.value is not None]
        if len(valid_trials) > 0:
            best_trial = max(valid_trials, key=lambda t: t.value)
            best_params = best_trial.params
            best_value = best_trial.value
        else:
            best_params = {}
            best_value = 0.0
    else:
        best_params = study.best_params
        best_value = study.best_value

    return {
        "best_params": best_params,
        "best_value": best_value,
        "study": study
    }


def check_robustness(
    is_stats: dict,
    oos_stats: dict,
    tolerated_drawdown: float
) -> Tuple[float, bool]:
    """
    Evaluates the performance drift (Robustness Index) of optimized parameters.
    
    Args:
        is_stats: Metrics dictionary on the In-Sample training block.
        oos_stats: Metrics dictionary on the Out-Of-Sample test block.
        tolerated_drawdown: Maximum tolerated drawdown fraction.
        
    Returns:
        A tuple (robustness_index, is_valid) where is_valid is True if the segment
        passes robustness tests, and False if rejected.
    """
    sortino_is = is_stats.get("sortino_ratio", 0.0)
    sortino_oos = oos_stats.get("sortino_ratio", 0.0)
    
    ret_is = is_stats.get("total_return", 0.0)
    ret_oos = oos_stats.get("total_return", 0.0)
    
    # Calculate Robustness Index (RI)
    if sortino_is == 0.0:
        ri = 999.0 if sortino_oos > 0.0 else 0.0
    else:
        ri = sortino_oos / sortino_is
        
    is_valid = True
    
    # Rejection Rule 1: Out-of-sample drift limits
    if ri < 0.5 or ri > 1.5:
        is_valid = False
        
    # Rejection Rule 2: Sign drift (OOS is losing money while IS was profitable)
    if ret_is > 0.0 and ret_oos < 0.0:
        is_valid = False
        
    # Rejection Rule 3: Extreme drawdown (OOS resulted in bankruptcy / liquidation)
    if oos_stats.get("max_drawdown", 0.0) >= 1.0:
        is_valid = False
        
    return float(ri), is_valid


def stitch_oos_performance(
    oos_equities: List[np.ndarray],
    initial_balance: float = 10000.0
) -> np.ndarray:
    """
    Stitches discontinuous Out-Of-Sample equity curves into a single, continuous series.
    Applies multiplicative scaling at boundaries to preserve relative returns and avoid gaps.
    
    Args:
        oos_equities: A list of 1D NumPy arrays containing sequential OOS equities.
        initial_balance: Reference starting value.
        
    Returns:
        A stitched continuous 1D NumPy array of equity curves.
    """
    if not oos_equities:
        return np.array([initial_balance], dtype=np.float64)
        
    stitched_list = []
    curr_multiplier = 1.0
    
    for idx, eq in enumerate(oos_equities):
        if len(eq) == 0:
            continue
            
        eq_arr = np.array(eq, dtype=np.float64)
        
        if idx == 0:
            # Scale first segment to start at initial_balance
            if eq_arr[0] > 0.0:
                curr_multiplier = initial_balance / eq_arr[0]
            else:
                curr_multiplier = 1.0
        else:
            # Multiplicative stitching transition boundary matching
            last_val = stitched_list[-1]
            start_val = eq_arr[0]
            if start_val > 0.0:
                curr_multiplier = last_val / start_val
            else:
                curr_multiplier = 0.0
                
        scaled_eq = eq_arr * curr_multiplier
        stitched_list.extend(scaled_eq.tolist())
        
    return np.array(stitched_list, dtype=np.float64)
