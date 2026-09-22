"""
TIER 4 - TRAP DETECTOR


Detects bull traps, bear traps, false breakouts, and stop hunts.
A trap is when price fakes a move to trigger entries/stops, then reverses.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class TrapDetector(BaseEngine):
    """Tier 4: Trap & False Breakout Detector"""
    
    ENGINE_NAME = "trap_detector"
    ENGINE_VERSION = "1.0.0"
    TIER = 4
    MIN_CANDLES = 50
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        false_breakout, fb_type = self._detect_false_breakout(candles_df)
        stop_hunt = self._detect_stop_hunt(candles_df)
        rejection_wick = self._detect_rejection_wick(candles_df)
        
        # Determine trap
        trap_detected = false_breakout or stop_hunt or rejection_wick
        
        trap_type = 'NONE'
        if false_breakout:
            trap_type = fb_type
        elif stop_hunt:
            trap_type = 'STOP_HUNT'
        elif rejection_wick:
            trap_type = 'REJECTION'
        
        trap_score = self._calculate_trap_score(
            false_breakout, stop_hunt, rejection_wick, candles_df
        )
        
        return {
            'trap_detected': bool(trap_detected),
            'trap_type': trap_type,
            'trap_score': trap_score,
            'false_breakout': bool(false_breakout),
            'stop_hunt': bool(stop_hunt),
            'rejection_wick': bool(rejection_wick),
            'confidence': 70 if trap_detected else 60,
        }
    
    def _detect_false_breakout(self, df):
        """Detect price breaking a level then reversing"""
        try:
            recent = df.tail(20)
            highs = recent['high'].values
            lows = recent['low'].values
            closes = recent['close'].values
            
            # Recent high/low (excluding last 3 candles)
            prior_high = max(highs[:-3])
            prior_low = min(lows[:-3])
            
            last_3_high = max(highs[-3:])
            last_3_low = min(lows[-3:])
            last_close = closes[-1]
            
            # Bull trap: broke above prior high, then closed back below
            if last_3_high > prior_high and last_close < prior_high:
                return True, 'BULL_TRAP'
            
            # Bear trap: broke below prior low, then closed back above
            if last_3_low < prior_low and last_close > prior_low:
                return True, 'BEAR_TRAP'
            
            return False, 'NONE'
        except Exception as e:
            raise

    
    def _detect_stop_hunt(self, df):
        """Detect quick spike beyond a level that retraces fast"""
        try:
            recent = df.tail(10)
            ranges = recent['high'] - recent['low']
            avg_range = ranges.mean()
            
            last = recent.iloc[-1]
            last_range = last['high'] - last['low']
            
            # Large range candle with close near middle/opposite end = stop hunt
            if last_range > avg_range * 2:
                body = abs(last['close'] - last['open'])
                if body < last_range * 0.4:  # Small body, big wicks
                    return True
            return False
        except Exception as e:
            raise

    
    def _detect_rejection_wick(self, df):
        """Detect strong rejection wick on last candle"""
        try:
            last = df.iloc[-1]
            body = abs(last['close'] - last['open'])
            upper_wick = last['high'] - max(last['open'], last['close'])
            lower_wick = min(last['open'], last['close']) - last['low']
            total = last['high'] - last['low']
            
            if total == 0:
                return False
            
            # Strong rejection if one wick > 60% of range
            if upper_wick / total > 0.6 or lower_wick / total > 0.6:
                return True
            return False
        except Exception as e:
            raise

    
    def _calculate_trap_score(self, fb, sh, rw, df) -> int:
        """Score 0-100 for trap likelihood"""
        score = 0
        if fb:
            score += 50
        if sh:
            score += 30
        if rw:
            score += 25
        return min(100, score)
    
