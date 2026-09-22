from typing import Dict, Any
import pandas as pd

from data_evaluate.orchestration.base_engine import BaseEngine


class MarketStructureEngine(BaseEngine):
    """วิเคราะห์โครงสร้างราคา (HH, HL, LL, LH) เพื่อจำแนกสภาวะตลาด"""

    ENGINE_NAME = "market_structure"
    ENGINE_VERSION = "1.0.0"
    TIER = 3
    MIN_CANDLES = 15

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.lookback = 15  # ดูย้อนหลัง 15 แท่งเพื่อความแม่นยำ

    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        # operate on the last `lookback` rows
        if candles_df is None or not isinstance(candles_df, pd.DataFrame) or candles_df.empty or len(candles_df) < self.lookback:
            raise ValueError("FAIL-FAST: Neutral state removed")

        df = candles_df.copy()
        recent = df.tail(self.lookback)

        highs = recent['high'].tolist()
        lows = recent['low'].tolist()

        # split into recent, previous, and older windows
        recent_highs = highs[-5:]
        recent_lows = lows[-5:]
        prev_highs = highs[-10:-5] or highs[:max(0, len(highs)-5)]
        prev_lows = lows[-10:-5] or lows[:max(0, len(lows)-5)]
        older_highs = highs[-15:-10] or highs[:max(0, len(highs)-10)]
        older_lows = lows[-15:-10] or lows[:max(0, len(lows)-10)]

        try:
            current_high = max(recent_highs)
            prev_high = max(prev_highs)
            older_high = max(older_highs)
            current_low = min(recent_lows)
            prev_low = min(prev_lows)
            older_low = min(older_lows)
        except ValueError:
            raise ValueError("FAIL-FAST: Neutral state removed")

        # วิเคราะห์โครงสร้าง
        if current_high > prev_high and current_low > prev_low:
            structure = "BULLISH"
            regime = "STRONG_TREND" if (current_high - prev_high) > (prev_high - older_high) else "WEAK_TREND"
        elif current_high < prev_high and current_low < prev_low:
            structure = "BEARISH"
            regime = "STRONG_TREND" if (prev_low - current_low) > (older_low - prev_low) else "WEAK_TREND"
        else:
            structure = "RANGING"
            avg_range = recent['high'].sub(recent['low']).tail(5).mean()
            if avg_range < (recent['high'].sub(recent['low']).mean()) * 0.8:
                regime = "CHOPPY"
            else:
                regime = "RANGING"

        # เช็ค Breakout
        if abs(current_high - prev_high) > (prev_high * 0.001):  # 0.1% move
            if current_high > prev_high and structure == "BULLISH":
                regime = "BREAKOUT"

        return {
            "status": "ACTIVE",
            "regime": regime,
            "structure": structure,
            "last_high": float(current_high),
            "last_low": float(current_low),
            "trend_strength": float(abs(current_high - prev_high) + abs(current_low - prev_low)),
        }
