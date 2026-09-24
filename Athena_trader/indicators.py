import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List

def calculate_bb_pct_b(df: pd.DataFrame, period: int = 41, std_mult: float = 2.0) -> pd.DataFrame:
    close = df['close']
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = mid + (std * std_mult)
    lower = mid - (std * std_mult)
    
    diff = upper - lower
    diff = diff.replace(0, np.nan)
    pct_b = (close - lower) / diff
    
    result = df.copy()
    result['bb_mid'] = mid
    result['bb_upper'] = upper
    result['bb_lower'] = lower
    result['bb_pct_b'] = pct_b
    return result

def calculate_stochastic(df: pd.DataFrame, k_period: int = 13, d_period: int = 3, smooth_k: int = 10) -> pd.DataFrame:
    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()
    
    denom = high_max - low_min
    denom = denom.replace(0, np.nan)
    raw_k = 100 * ((df['close'] - low_min) / denom)
    
    slow_k = raw_k.rolling(window=smooth_k).mean()
    slow_d = slow_k.rolling(window=d_period).mean()
    
    result = df.copy()
    result['sto_k'] = slow_k
    result['sto_d'] = slow_d
    return result

def calculate_ma_crossover(df: pd.DataFrame, fast_period: int = 3, slow_period: int = 6) -> pd.DataFrame:
    result = df.copy()
    result['ma_fast_ema'] = df['close'].ewm(span=fast_period, adjust=False).mean()
    result['ma_slow_sma'] = df['close'].rolling(window=slow_period).mean()
    return result

def calculate_macd(df: pd.DataFrame, fast: int = 15, slow: int = 35, signal: int = 9) -> pd.DataFrame:
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    
    result = df.copy()
    result['macd_line'] = macd_line
    result['macd_signal'] = signal_line
    result['macd_hist'] = hist
    return result

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    
    result = df.copy()
    result['rsi'] = rsi
    return result

def calculate_parabolic_sar(df: pd.DataFrame, af_step: float = 0.09, af_max: float = 0.04) -> pd.DataFrame:
    length = len(df)
    sar = np.zeros(length)
    if length < 2:
        res = df.copy()
        res['psar'] = df['close']
        res['psar_dir'] = 1
        return res
        
    high = df['high'].values
    low = df['low'].values
    
    is_bull = high[1] >= high[0]
    af = af_step
    ep = high[0] if is_bull else low[0]
    sar[0] = low[0] if is_bull else high[0]
    direction = np.zeros(length, dtype=int)
    direction[0] = 1 if is_bull else -1
    
    for i in range(1, length):
        prev_sar = sar[i-1]
        if is_bull:
            curr_sar = prev_sar + af * (ep - prev_sar)
            curr_sar = min(curr_sar, low[i-1], low[max(0, i-2)])
            if low[i] < curr_sar:
                is_bull = False
                curr_sar = ep
                ep = low[i]
                af = af_step
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            curr_sar = prev_sar + af * (ep - prev_sar)
            curr_sar = max(curr_sar, high[i-1], high[max(0, i-2)])
            if high[i] > curr_sar:
                is_bull = True
                curr_sar = ep
                ep = high[i]
                af = af_step
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)
        sar[i] = curr_sar
        direction[i] = 1 if is_bull else -1
        
    result = df.copy()
    result['psar'] = sar
    result['psar_dir'] = direction
    return result

def detect_euf_levels(df: pd.DataFrame, lookback: int = 50) -> Dict[str, List[float]]:
    resistances = []
    supports = []
    
    sub = df.tail(lookback).reset_index(drop=True)
    n = len(sub)
    if n < 3:
        return {"resistances": [], "supports": []}
        
    for i in range(1, n):
        prev = sub.iloc[i-1]
        curr = sub.iloc[i]
        
        # RG DOWN (Bearish Engulfing): Prev Green, Curr Red, Curr Body engulfs Prev Body
        if prev['close'] > prev['open'] and curr['close'] < curr['open']:
            if curr['open'] >= prev['close'] and curr['close'] <= prev['open']:
                resistances.append(float(max(prev['high'], curr['high'])))
                
        # GR UP (Bullish Engulfing): Prev Red, Curr Green, Curr Body engulfs Prev Body
        elif prev['close'] < prev['open'] and curr['close'] > curr['open']:
            if curr['open'] <= prev['close'] and curr['close'] >= prev['open']:
                supports.append(float(min(prev['low'], curr['low'])))
                
    return {
        "resistances": sorted(list(set(resistances)))[-3:],
        "supports": sorted(list(set(supports)))[:3]
    }

def detect_fractals(df: pd.DataFrame) -> Tuple[List[float], List[float]]:
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    fractal_highs = []
    fractal_lows = []
    
    for i in range(2, n - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            fractal_highs.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            fractal_lows.append(lows[i])
            
    return fractal_highs, fractal_lows
