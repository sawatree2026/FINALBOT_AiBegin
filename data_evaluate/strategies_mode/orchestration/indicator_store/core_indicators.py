import pandas as pd
import numpy as np

class CoreIndicators:
    @staticmethod
    def calculate_ema(close_series: pd.Series, periods: list, round_decimals: int) -> dict:
        res = {}
        for p in periods:
            res[f'ema{p}'] = round(close_series.ewm(span=p, adjust=False).mean().iloc[-1], round_decimals)
        return res

    @staticmethod
    def calculate_bb(close_series: pd.Series, period: int, round_decimals: int, require_100: bool = False) -> dict:
        sma = close_series.rolling(window=period, min_periods=1).mean()
        std = close_series.rolling(window=period, min_periods=1).std(ddof=0)
        if std.iloc[-1] != std.iloc[-1]:
            raise ValueError("FAIL-FAST: Bollinger std is NaN - zero substitution is forbidden")
        
        bb_upper = round((sma + 2 * std).iloc[-1], round_decimals)
        bb_lower = round((sma - 2 * std).iloc[-1], round_decimals)
        
        res = {
            'bb_upper': bb_upper,
            'bb_lower': bb_lower
        }
        
        if require_100:
            bbw_series = (sma + 2 * std) - (sma - 2 * std)
            res['bb_width'] = round(bbw_series.iloc[-1], round_decimals)
            if len(bbw_series) < 100:
                raise ValueError("Not enough data to calculate bbw_sma_100")
            res['bbw_sma_100'] = round(bbw_series.rolling(window=100, min_periods=1).mean().iloc[-1], round_decimals)
            
        return res

    @staticmethod
    def calc_rsi_series(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
        if gain.iloc[-1] != gain.iloc[-1]:
            raise ValueError("FAIL-FAST: RSI gain is NaN - zero substitution is forbidden")
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean().replace(0, 1e-9).fillna(1e-9)
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calc_rsi(series: pd.Series, period: int) -> float:
        rsi = CoreIndicators.calc_rsi_series(series, period)
        if pd.isna(rsi.iloc[-1]):
            raise ValueError("RSI is NaN")
        return round(rsi.iloc[-1], 2)

    @staticmethod
    def calc_macd_series(close_series: pd.Series) -> tuple:
        exp12 = close_series.ewm(span=12, adjust=False).mean()
        exp26 = close_series.ewm(span=26, adjust=False).mean()
        macd_line = exp12 - exp26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal
        return macd_line, macd_signal, macd_hist

    @staticmethod
    def calculate_macd(close_series: pd.Series, round_decimals: int, include_hist: bool = True) -> dict:
        macd_line, macd_signal, macd_hist = CoreIndicators.calc_macd_series(close_series)
        res = {
            'macd': round(macd_line.iloc[-1], round_decimals),
            'macd_signal': round(macd_signal.iloc[-1], round_decimals)
        }
        if include_hist:
            res['macd_hist'] = round(macd_hist.iloc[-1], round_decimals)
        return res

    @staticmethod
    def calculate_stochastic(close_series: pd.Series, high_series: pd.Series, low_series: pd.Series) -> dict:
        low_min = low_series.rolling(window=13, min_periods=1).min()
        high_max = high_series.rolling(window=13, min_periods=1).max()
        stoch_k_raw = 100 * (close_series - low_min) / (high_max - low_min + 1e-9)
        stoch_k = stoch_k_raw.rolling(window=10, min_periods=1).mean()
        stoch_d = stoch_k.rolling(window=3, min_periods=1).mean()
        return {
            'stoch_k': round(stoch_k.iloc[-1], 2),
            'stoch_d': round(stoch_d.iloc[-1], 2)
        }

    @staticmethod
    def calculate_stochastic_snapshot(
        close_series: pd.Series,
        high_series: pd.Series,
        low_series: pd.Series,
        k_period: int = 13,
        smoothing: int = 10,
        d_period: int = 3,
    ) -> dict:
        """Return the complete Believe stochastic snapshot without defaults."""
        if len(close_series) < k_period + smoothing + d_period - 2:
            raise ValueError("FAIL-FAST: insufficient candles for stochastic snapshot")
        lowest = low_series.rolling(k_period, min_periods=k_period).min()
        highest = high_series.rolling(k_period, min_periods=k_period).max()
        span = highest - lowest
        if span.iloc[-1] == 0 or pd.isna(span.iloc[-1]):
            raise ValueError("FAIL-FAST: stochastic range is zero or undefined")
        raw = 100 * (close_series - lowest) / span
        k = raw.rolling(smoothing, min_periods=smoothing).mean()
        d = k.rolling(d_period, min_periods=d_period).mean()
        if pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-1]):
            raise ValueError("FAIL-FAST: stochastic snapshot is undefined")
        previous_k = float(k.iloc[-2])
        previous_d = float(d.iloc[-2])
        current_k = float(k.iloc[-1])
        current_d = float(d.iloc[-1])
        return {
            "stoch_k": round(current_k, 2),
            "stoch_d": round(current_d, 2),
            "stoch_prev_k": round(previous_k, 2),
            "stoch_prev_d": round(previous_d, 2),
            "stoch_cross": (
                "UP" if previous_k <= previous_d and current_k > current_d
                else "DOWN" if previous_k >= previous_d and current_k < current_d
                else "NONE"
            ),
            "stoch_cross_50": (
                "UP" if previous_k < 50 <= current_k
                else "DOWN" if previous_k > 50 >= current_k
                else "NONE"
            ),
            "stoch_hook_confirmed": bool(
                (previous_k <= previous_d and current_k > current_d)
                or (previous_k >= previous_d and current_k < current_d)
            ),
            "stoch_tangled": bool((k.tail(3) - d.tail(3)).abs().max() < 2),
        }
