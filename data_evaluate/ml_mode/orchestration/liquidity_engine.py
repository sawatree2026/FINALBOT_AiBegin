"""
TIER 4 - LIQUIDITY ENGINE


Detects liquidity zones, equal highs/lows (where stops cluster),
and liquidity sweeps.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List

from data_evaluate.orchestration.base_engine import BaseEngine


class LiquidityEngine(BaseEngine):
    """Tier 4: Liquidity Engine"""
    
    ENGINE_NAME = "liquidity_engine"
    ENGINE_VERSION = "1.0.0"
    TIER = 4
    MIN_CANDLES = 50
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        equal_highs = self._find_equal_highs(candles_df)
        equal_lows = self._find_equal_lows(candles_df)
        liquidity_sweep, sweep_type = self._detect_sweep(candles_df)
        
        # Liquidity zones (where stops likely cluster)
        liquidity_above = len(equal_highs) > 0
        liquidity_below = len(equal_lows) > 0
        
        return {
            'equal_highs': equal_highs,
            'equal_lows': equal_lows,
            'liquidity_above': bool(liquidity_above),
            'liquidity_below': bool(liquidity_below),
            'liquidity_sweep_detected': bool(liquidity_sweep),
            'sweep_type': sweep_type,
            'liquidity_score': self._score_liquidity(equal_highs, equal_lows),
            'confidence': 65,
        }
    
    def _find_equal_highs(self, df, tolerance=0.0008) -> List[float]:
        """Find clusters of similar highs (resting liquidity)"""
        try:
            highs = df['high'].tail(50).values
            equal = []
            
            for i in range(len(highs)):
                for j in range(i + 1, len(highs)):
                    if highs[i] == 0:
                        continue
                    diff = abs(highs[i] - highs[j]) / highs[i]
                    if diff < tolerance:
                        level = round((highs[i] + highs[j]) / 2, 5)
                        if level not in equal:
                            equal.append(level)
            
            return sorted(equal, reverse=True)[:3]
        except Exception as e:
            raise

    
    def _find_equal_lows(self, df, tolerance=0.0008) -> List[float]:
        """Find clusters of similar lows (resting liquidity)"""
        try:
            lows = df['low'].tail(50).values
            equal = []
            
            for i in range(len(lows)):
                for j in range(i + 1, len(lows)):
                    if lows[i] == 0:
                        continue
                    diff = abs(lows[i] - lows[j]) / lows[i]
                    if diff < tolerance:
                        level = round((lows[i] + lows[j]) / 2, 5)
                        if level not in equal:
                            equal.append(level)
            
            return sorted(equal)[:3]
        except Exception as e:
            raise

    
    def _detect_sweep(self, df):
        """Detect liquidity sweep: price spikes past a level then reverses"""
        if not isinstance(df, pd.DataFrame):
            import logging
            logging.error(f"LiquidityEngine._detect_sweep expected pd.DataFrame, got {type(df)}")
            raise TypeError(f"LiquidityEngine._detect_sweep expected pd.DataFrame, got {type(df)}")
            
        try:
            if len(df) < 5:
                return False, 'NONE'
                
            recent = df.tail(15)
            highs = recent['high'].values
            lows = recent['low'].values
            closes = recent['close'].values
            
            # Prior swing levels
            prior_high = max(highs[:-2])
            prior_low = min(lows[:-2])
            
            last_high = highs[-1]
            last_low = lows[-1]
            last_close = closes[-1]
            
            # Sweep high: poked above prior high but closed below
            if last_high > prior_high and last_close < prior_high:
                return True, 'SWEEP_HIGH'
            
            # Sweep low: poked below prior low but closed above
            if last_low < prior_low and last_close > prior_low:
                return True, 'SWEEP_LOW'
            
            return False, 'NONE'
        except Exception as e:
            raise

    
    def _score_liquidity(self, equal_highs, equal_lows) -> int:
        """Score liquidity presence 0-100"""
        score = 30
        score += len(equal_highs) * 12
        score += len(equal_lows) * 12
        return min(100, score)
    
