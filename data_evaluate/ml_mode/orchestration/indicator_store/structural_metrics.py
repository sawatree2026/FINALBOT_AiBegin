import pandas as pd
import numpy as np

class StructuralMetrics:
    @staticmethod
    def calculate_atr(high_series: pd.Series, low_series: pd.Series, close_series: pd.Series, round_decimals: int, extended: bool = True) -> dict:
        high_low = high_series - low_series
        high_close = np.abs(high_series - close_series.shift())
        low_close = np.abs(low_series - close_series.shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_series = ranges.ewm(alpha=1/14, adjust=False).mean().dropna()
        
        if not extended:
            if atr_series.empty:
                raise ValueError("M1 ATR series is empty after dropna — cannot compute atr14")
            atr14 = atr_series.iloc[-1]
            if np.isnan(atr14):
                raise ValueError("M1 ATR14 is NaN — data may be corrupt")
            return {'atr14': round(atr14, round_decimals)}

        res = {}
        if len(atr_series) > 0:
            current_atr = atr_series.iloc[-1]
            res['atr14'] = round(current_atr, round_decimals)
            res['atr_percentile'] = round((np.sum(atr_series <= current_atr) / len(atr_series)) * 100, 2)
            atr_std = atr_series.std()
            atr_std = 0 if pd.isna(atr_std) else atr_std
            res['atr_zscore'] = round((current_atr - atr_series.mean()) / (atr_std + 1e-9), 2)
            
            recent_atr_avg = atr_series.tail(10).mean()
            past_atr_avg = atr_series.iloc[-20:-10].mean() if len(atr_series) >= 20 else recent_atr_avg
            res['atr_recent_avg'] = round(recent_atr_avg, round_decimals)
            res['atr_past_avg'] = round(past_atr_avg, round_decimals)
        else:
            res['atr14'] = 0.0
            res['atr_percentile'] = 50.0
            res['atr_zscore'] = 0.0
            res['atr_recent_avg'] = 0.0
            res['atr_past_avg'] = 0.0
        return res

    @staticmethod
    def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict:
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        
        # Wilder's Smoothing (EMA with alpha = 1/period)
        tr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
        plus_dm_smooth = pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean()
        minus_dm_smooth = pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean()
        
        # DI+
        di_plus = 100 * (plus_dm_smooth / (tr_smooth + 1e-9))
        di_minus = 100 * (minus_dm_smooth / (tr_smooth + 1e-9))
        
        # DX
        dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus + 0.000001)
        
        # ADX = Smooth DX
        adx = dx.ewm(alpha=1/period, adjust=False).mean()
        
        # Fill NaN
        adx = adx.fillna(0)
        di_plus = di_plus.fillna(0)
        di_minus = di_minus.fillna(0)
        dx = dx.fillna(0)
        
        return {
            'adx': round(adx.iloc[-1], 2),
            'di_plus': round(di_plus.iloc[-1], 2),
            'di_minus': round(di_minus.iloc[-1], 2),
            'dx': round(dx.iloc[-1], 2)
        }

    @staticmethod
    def calculate_volume_metrics(volume_series: pd.Series, period: int = 20, extended: bool = True) -> dict:
        volume_ma20 = volume_series.rolling(window=period, min_periods=1).mean()
        current_volume = volume_series.iloc[-1]
        volume_ratio = min(round(current_volume / (volume_ma20.iloc[-1] + 0.000001), 3), 10.0)
        
        res = {
            'volume': current_volume,
            'volume_ratio': volume_ratio
        }
        if extended:
            res['volume_ma20'] = round(volume_ma20.iloc[-1], 2)
            res['volume_spike'] = bool(volume_ratio > 2.0)
            
        return res

    @staticmethod
    def calc_slope(series: pd.Series, period: int) -> float:
        if len(series) < period:
            return 0.0
        y = series.tail(period).values
        if np.any(np.isnan(y)):
            raise ValueError(f"NaN detected in slope series (period={period}) — cannot compute linear regression")
        x = np.arange(period)
        slope, _ = np.polyfit(x, y, 1)
        if np.isnan(slope):
            raise ValueError(f"np.polyfit returned NaN slope — data may be degenerate")
        return slope

    @staticmethod
    def calculate_box_metrics(high_series: pd.Series, low_series: pd.Series, atr14: float) -> dict:
        highs = high_series.tail(50).values
        lows = low_series.tail(50).values
        if len(highs) >= 20:
            ref_high = max(highs[-20:])
            ref_low = min(lows[-20:])
            ref_range = ref_high - ref_low
            box_dur = 0
            for i in range(len(highs) - 1, -1, -1):
                if ref_low <= highs[i] <= ref_high and ref_low <= lows[i] <= ref_high:
                    box_dur += 1
                else:
                    break
            
            if atr14 <= 0:
                raise ValueError(f"ATR14 is zero or negative ({atr14}) — cannot compute box_tightness")
            box_tightness = round(ref_range / atr14, 2)
            return {'box_duration': box_dur, 'box_tightness': box_tightness}
        else:
            return {'box_duration': 10, 'box_tightness': 2.5}
