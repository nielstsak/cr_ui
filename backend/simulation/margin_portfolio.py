import numpy as np
import numba


@numba.njit(nogil=True, parallel=False)
def simulate_margin_portfolio_jit(
    close: np.ndarray,
    signals: np.ndarray,
    initial_balance: float,
    fee_rate: float,
    slippage_rate: float,
    mmr: float,
    leverage: float
):
    """
    Core JIT-compiled loop simulating a cross-margin single-asset trading portfolio.
    
    Manages step-by-step Mark-to-Market Unrealized PnL, equity calculation,
    execution slippage, trading fees, and forced liquidation triggers.
    
    Args:
        close: 1D array of close prices (float64).
        signals: 1D array of target position signals (-1=Short, 0=Cash, 1=Long).
        initial_balance: Starting cash balance.
        fee_rate: Execution fee rate (e.g. 0.0004 for 0.04%).
        slippage_rate: Execution slippage penalty rate (e.g. 0.0005 for 0.05%).
        mmr: Maintenance Margin Requirement (e.g. 0.05 for 5%).
        leverage: Fixed leverage factor applied to equity on position changes.
        
    Returns:
        A tuple of 1D arrays:
        - equity: Portfolio valuation over time (balance + UPnL).
        - balance: Realized cash balance over time.
        - position: Active contract size size (positive for Long, negative for Short).
        - entry_price: Average entry price of the active position.
        - liquidation: 1 at index t if forced liquidation occurred, 0 otherwise.
    """
    n = len(close)
    
    equity = np.empty(n, dtype=np.float64)
    balance = np.empty(n, dtype=np.float64)
    position = np.empty(n, dtype=np.float64)
    entry_price = np.empty(n, dtype=np.float64)
    liquidation = np.zeros(n, dtype=np.int32)
    
    curr_balance = initial_balance
    curr_q = 0.0
    curr_entry = 0.0
    
    for t in range(n):
        p_close = close[t]
        sig = signals[t]
        
        # 1. Compute Mark-to-Market Unrealized PnL (UPnL) from yesterday's position
        upnl = 0.0
        if curr_q > 0.0:
            upnl = curr_q * (p_close - curr_entry)
        elif curr_q < 0.0:
            upnl = abs(curr_q) * (curr_entry - p_close)
            
        # 2. Evaluate temporary Equity & Maintenance Margin (MM) requirement
        temp_equity = curr_balance + upnl
        mm = abs(curr_q * p_close) * mmr
        
        # 3. Check for Forced Liquidation
        if temp_equity <= mm and curr_q != 0.0:
            # Force close all contracts at market price penalized by slippage
            if curr_q > 0.0:
                p_exec = p_close * (1.0 - slippage_rate)
                realized_pnl = curr_q * (p_exec - curr_entry)
            else:
                p_exec = p_close * (1.0 + slippage_rate)
                realized_pnl = abs(curr_q) * (curr_entry - p_exec)
                
            fees = abs(curr_q) * p_exec * fee_rate
            curr_balance = curr_balance + realized_pnl - fees
            
            # Reset balance to zero if it falls below 0 (negative equity/debt)
            if curr_balance < 0.0:
                curr_balance = 0.0
                
            curr_q = 0.0
            curr_entry = 0.0
            liquidation[t] = 1
            
            equity[t] = curr_balance
            balance[t] = curr_balance
            position[t] = 0.0
            entry_price[t] = 0.0
            continue
            
        # 4. Process Target Signal Changes
        # Compute target quantity based on leveraged equity
        target_notional = temp_equity * leverage
        target_q = (target_notional / p_close) * sig
        
        if target_q != curr_q:
            dq = target_q - curr_q
            # Slippage execution adjustments
            if dq > 0.0:
                p_exec = p_close * (1.0 + slippage_rate)
            else:
                p_exec = p_close * (1.0 - slippage_rate)
                
            fees = abs(dq) * p_exec * fee_rate
            
            if curr_q == 0.0:
                # Open new position
                curr_balance -= fees
                curr_q = target_q
                curr_entry = p_exec
            else:
                # Active position modification
                if curr_q > 0.0:
                    if target_q > 0.0:
                        if target_q > curr_q:
                            # Increase Long position
                            curr_balance -= fees
                            curr_entry = (curr_q * curr_entry + dq * p_exec) / target_q
                            curr_q = target_q
                        else:
                            # Reduce Long position
                            q_closed = curr_q - target_q
                            realized_pnl = q_closed * (p_exec - curr_entry)
                            curr_balance = curr_balance + realized_pnl - fees
                            curr_q = target_q
                            # Entry price remains unchanged on reductions
                    elif target_q < 0.0:
                        # Flip Long to Short
                        # Close Long
                        realized_pnl = curr_q * (p_exec - curr_entry)
                        curr_balance = curr_balance + realized_pnl - fees
                        # Open Short at p_exec
                        curr_q = target_q
                        curr_entry = p_exec
                    else:
                        # Close position completely
                        realized_pnl = curr_q * (p_exec - curr_entry)
                        curr_balance = curr_balance + realized_pnl - fees
                        curr_q = 0.0
                        curr_entry = 0.0
                else:  # curr_q < 0.0 (Short)
                    if target_q < 0.0:
                        if abs(target_q) > abs(curr_q):
                            # Increase Short position
                            curr_balance -= fees
                            curr_entry = (abs(curr_q) * curr_entry + abs(dq) * p_exec) / abs(target_q)
                            curr_q = target_q
                        else:
                            # Reduce Short position
                            q_closed = curr_q - target_q
                            realized_pnl = abs(q_closed) * (curr_entry - p_exec)
                            curr_balance = curr_balance + realized_pnl - fees
                            curr_q = target_q
                    elif target_q > 0.0:
                        # Flip Short to Long
                        # Close Short
                        realized_pnl = abs(curr_q) * (curr_entry - p_exec)
                        curr_balance = curr_balance + realized_pnl - fees
                        # Open Long at p_exec
                        curr_q = target_q
                        curr_entry = p_exec
                    else:
                        # Close position completely
                        realized_pnl = abs(curr_q) * (curr_entry - p_exec)
                        curr_balance = curr_balance + realized_pnl - fees
                        curr_q = 0.0
                        curr_entry = 0.0
                        
            if curr_balance < 0.0:
                curr_balance = 0.0
                curr_q = 0.0
                curr_entry = 0.0
                
        # 5. Record final metrics for this timestamp step
        step_upnl = 0.0
        if curr_q > 0.0:
            step_upnl = curr_q * (p_close - curr_entry)
        elif curr_q < 0.0:
            step_upnl = abs(curr_q) * (curr_entry - p_close)
            
        step_equity = curr_balance + step_upnl
        if step_equity < 0.0:
            step_equity = 0.0
            curr_balance = 0.0
            curr_q = 0.0
            curr_entry = 0.0
            
        equity[t] = step_equity
        balance[t] = curr_balance
        position[t] = curr_q
        entry_price[t] = curr_entry
        
    return equity, balance, position, entry_price, liquidation


def simulate_margin_portfolio(
    close: np.ndarray,
    signals: np.ndarray,
    initial_balance: float = 10000.0,
    fee_rate: float = 0.0004,
    slippage_rate: float = 0.0005,
    mmr: float = 0.05,
    leverage: float = 1.0,
    annualization_factor: float = 365.25 * 1440.0,  # Defaults to 1-minute steps per year
    tolerated_drawdown: float = 0.20
) -> dict:
    """
    Public wrapper function for the cross-margin portfolio simulator.
    Calculates detailed performance statistics.
    
    Args:
        close: 1D array of close prices (float64).
        signals: 1D array of target position signals (-1=Short, 0=Cash, 1=Long).
        initial_balance: Starting cash balance.
        fee_rate: Execution fee rate.
        slippage_rate: Execution slippage penalty rate.
        mmr: Maintenance Margin Requirement.
        leverage: Fixed leverage factor.
        annualization_factor: Number of observation periods in one calendar year.
        tolerated_drawdown: Maximum tolerated drawdown fraction for J-Score penalty.
        
    Returns:
        A dict containing raw time series and statistics:
        {
            "equity": np.ndarray,
            "balance": np.ndarray,
            "position": np.ndarray,
            "entry_price": np.ndarray,
            "liquidation": np.ndarray,
            "total_return": float,
            "annualized_return": float,
            "max_drawdown": float,
            "downside_deviation": float,
            "sortino_ratio": float,
            "composite_score": float
        }
    """
    close = close.astype(np.float64)
    signals = signals.astype(np.int32)
    
    equity, balance, position, entry_price, liquidation = simulate_margin_portfolio_jit(
        close, signals, initial_balance, fee_rate, slippage_rate, mmr, leverage
    )
    
    n = len(close)
    
    # 1. Total Return
    total_return = (equity[-1] - initial_balance) / initial_balance
    
    # 2. Annualized Return
    if total_return <= -1.0:
        annualized_return = -1.0
    else:
        exponent = annualization_factor / n
        # Prevent float overflow (value > 700.0 inside exp will exceed float64 limit)
        if total_return > 0.0 and exponent * np.log(1.0 + total_return) > 700.0:
            annualized_return = 1e300
        else:
            annualized_return = (1.0 + total_return) ** exponent - 1.0
        
    # 3. Maximum Drawdown calculation
    peaks = np.maximum.accumulate(equity)
    dd = np.zeros(n)
    valid_peaks = peaks > 0.0
    dd[valid_peaks] = (peaks[valid_peaks] - equity[valid_peaks]) / peaks[valid_peaks]
    max_drawdown = np.max(dd)
    
    # 4. Period returns and downside deviation for Sortino Ratio
    returns = np.zeros(n - 1)
    for i in range(1, n):
        prev = equity[i - 1]
        returns[i - 1] = (equity[i] - prev) / prev if prev > 0.0 else 0.0
        
    # downside std deviation (RMS of negative returns over all periods N-1)
    neg_returns = returns[returns < 0.0]
    if len(neg_returns) == 0:
        downside_deviation = 0.0
    else:
        downside_deviation = np.sqrt(np.sum(neg_returns ** 2) / (n - 1))
        
    # 5. Sortino Ratio
    if downside_deviation == 0.0:
        sortino_ratio = 0.0
    else:
        mean_return = np.mean(returns)
        sortino_ratio = (mean_return / downside_deviation) * np.sqrt(annualization_factor)
        
    # 6. Composite Score J (with robust directional penalty gradient for genetic optimizers)
    if tolerated_drawdown <= 0.0:
        penalty = 1.0
    else:
        # Penalty term: negative if max_drawdown exceeds tolerated drawdown
        penalty = 1.0 - (max_drawdown / tolerated_drawdown) ** 2
        
    if sortino_ratio >= 0.0:
        composite_score = sortino_ratio * penalty
    else:
        # If Sortino is negative, we want the score to become MORE negative as drawdown increases.
        # So we multiply by (1 + ratio^2) to push it further negative.
        drawdown_ratio = max_drawdown / tolerated_drawdown if tolerated_drawdown > 0 else 0.0
        composite_score = sortino_ratio * (1.0 + drawdown_ratio ** 2)
        
    return {
        "equity": equity,
        "balance": balance,
        "position": position,
        "entry_price": entry_price,
        "liquidation": liquidation,
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "max_drawdown": float(max_drawdown),
        "downside_deviation": float(downside_deviation),
        "sortino_ratio": float(sortino_ratio),
        "composite_score": float(composite_score)
    }
