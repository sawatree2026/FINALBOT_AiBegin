"""
TIER 5 - TRANSITION ANALYZER


Detects when the market is transitioning between states/regimes.
Transitions are high-uncertainty periods.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class TransitionAnalyzer(BaseEngine):
    """Tier 5: Market Transition Analyzer"""
    
    ENGINE_NAME = "transition_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 5
    MIN_CANDLES = 60
    
    def get_neutral_state(self) -> Dict[str, Any]:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        volatility_shift = self._detect_volatility_shift(candles_df)
        momentum_shift = self._detect_momentum_shift(candles_df)
        structure_shift = self._detect_structure_shift(candles_df)
        
        in_transition = volatility_shift or momentum_shift or structure_shift
        
        transition_type = 'NONE'
        if volatility_shift:
            transition_type = 'VOLATILITY_REGIME_CHANGE'
        elif momentum_shift:
            transition_type = 'MOMENTUM_SHIFT'
        elif structure_shift:
            transition_type = 'STRUCTURE_BREAK'
        
        stability = self._calculate_stability(
            volatility_shift, momentum_shift, structure_shift
        )
        
        transition_risk = 'HIGH' if stability < 40 else ('MEDIUM' if in_transition or stability < 70 else 'LOW')
        
        return {
            'in_transition': bool(in_transition),
            'transition_type': transition_type,
            'volatility_shift': bool(volatility_shift),
            'momentum_shift': bool(momentum_shift),
            'structure_shift': bool(structure_shift),
            'stability_score': stability,
            'transition_risk': transition_risk,
            'is_stable': stability > 60,
            'confidence': 70,
        }
    
    def _detect_volatility_shift(self, df) -> bool:
        """Detect significant change in volatility"""
        try:
            ranges = (df['high'] - df['low']).tail(40)
            recent_vol = ranges.tail(10).mean()
            past_vol = ranges.iloc[-40:-10].mean()
            
            if past_vol == 0:
                return False
            
            ratio = recent_vol / past_vol
            # Significant shift if vol changed >50%
            return ratio > 1.5 or ratio < 0.6
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _detect_momentum_shift(self, df) -> bool:
        """Detect momentum direction/strength change"""
        try:
            closes = df['close'].tail(40)
            recent_slope = self._slope(closes.tail(10))
            past_slope = self._slope(closes.iloc[-40:-10])
            
            # Sign change = momentum shift
            if np.sign(recent_slope) != np.sign(past_slope):
                return True
            
            if abs(past_slope) == 0:
                return False
            if abs(recent_slope) / abs(past_slope) > 2.5:
                return True
            
            return False
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _detect_structure_shift(self, df) -> bool:
        """Detect break of recent structure"""
        try:
            recent = df.tail(30)
            prior_high = recent['high'].iloc[:-5].max()
            prior_low = recent['low'].iloc[:-5].min()
            
            last_close = recent['close'].iloc[-1]
            
            # Structure break if closed beyond prior range
            return last_close > prior_high or last_close < prior_low
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _slope(self, series) -> float:
        try:
            x = np.arange(len(series))
            return float(np.polyfit(x, series.values, 1)[0])
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _calculate_stability(self, vol_shift, mom_shift, struct_shift) -> int:
        """Stability score 0-100 (high = stable)"""
        score = 100
        if vol_shift:
            score -= 35
        if mom_shift:
            score -= 35
        if struct_shift:
            score -= 30
        return max(0, score)
    
