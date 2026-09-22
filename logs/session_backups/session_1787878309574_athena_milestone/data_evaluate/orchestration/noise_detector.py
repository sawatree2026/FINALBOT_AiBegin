"""
TIER 4 - NOISE DETECTOR


Measures market noise vs signal. High noise = unpredictable, avoid trading.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class NoiseDetector(BaseEngine):
    """Tier 4: Market Noise Detector"""
    
    ENGINE_NAME = "noise_detector"
    ENGINE_VERSION = "1.0.0"
    TIER = 4
    MIN_CANDLES = 50
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        choppiness = self._calculate_choppiness(candles_df)
        whipsaw = self._detect_whipsaw(candles_df)
        wick_noise = self._wick_noise_ratio(candles_df)
        direction_changes = self._count_direction_changes(candles_df)
        
        # Aggregate noise level
        noise_level = self._calculate_noise_level(
            choppiness, whipsaw, wick_noise, direction_changes
        )
        
        noise_category = self._categorize(noise_level)
        
        return {
            'noise_level': noise_level,
            'noise_category': noise_category,
            'choppiness_index': float(choppiness),
            'whipsaw_detected': bool(whipsaw),
            'wick_noise_ratio': float(wick_noise),
            'direction_changes': direction_changes,
            'is_clean': noise_level < 40,
            'confidence': 75,
        }
    
    def _calculate_choppiness(self, df) -> float:
        """Choppiness Index (0-100, high = choppy)"""
        try:
            period = 14
            recent = df.tail(period + 1)
            high = recent['high']
            low = recent['low']
            close = recent['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr_sum = tr.sum()
            
            price_range = high.max() - low.min()
            
            if price_range == 0 or atr_sum == 0:
                return 50.0
            
            chop = 100 * np.log10(atr_sum / price_range) / np.log10(period)
            return float(np.clip(chop, 0, 100))
        except Exception as e:
            raise

    
    def _detect_whipsaw(self, df) -> bool:
        """Detect rapid back-and-forth price action"""
        try:
            closes = df['close'].tail(10)
            changes = closes.diff().dropna()
            
            # Count sign changes
            signs = np.sign(changes)
            sign_changes = (signs != signs.shift(1)).sum()
            
            # Whipsaw if many direction changes
            return sign_changes >= 6
        except Exception as e:
            raise

    
    def _wick_noise_ratio(self, df) -> float:
        """Ratio of wicks to bodies (high = noisy)"""
        try:
            recent = df.tail(20)
            bodies = (recent['close'] - recent['open']).abs()
            ranges = recent['high'] - recent['low']
            wicks = ranges - bodies
            
            if bodies.sum() == 0:
                return 1.0
            
            return float(wicks.sum() / bodies.sum())
        except Exception as e:
            raise

    
    def _count_direction_changes(self, df) -> int:
        """Count how many times direction changed in last 20 candles"""
        try:
            closes = df['close'].tail(20)
            changes = closes.diff().dropna()
            signs = np.sign(changes)
            return int((signs != signs.shift(1)).sum())
        except Exception as e:
            raise

    
    def _calculate_noise_level(self, chop, whipsaw, wick_noise, dir_changes) -> int:
        """Aggregate noise score 0-100"""
        score = 0
        
        # Choppiness contribution (0-40)
        score += (chop / 100) * 40
        
        # Whipsaw contribution (0-20)
        if whipsaw:
            score += 20
        
        # Wick noise contribution (0-25)
        score += min(25, wick_noise * 12)
        
        # Direction changes contribution (0-15)
        score += min(15, dir_changes * 1.5)
        
        return int(min(100, max(0, score)))
    
    def _categorize(self, noise_level: int) -> str:
        if noise_level > 70:
            return 'VERY_NOISY'
        elif noise_level > 50:
            return 'NOISY'
        elif noise_level > 30:
            return 'MODERATE'
        return 'CLEAN'
    
