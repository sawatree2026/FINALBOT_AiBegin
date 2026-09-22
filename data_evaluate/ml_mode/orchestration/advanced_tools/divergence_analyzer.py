"""
TIER 4 - DIVERGENCE ANALYZER


Detects divergence between price and momentum indicators (RSI, MACD).
Divergence often precedes reversals.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine
from data_evaluate.orchestration.indicator_store.core_indicators import CoreIndicators


class DivergenceAnalyzer(BaseEngine):
    """Tier 4: Divergence Analyzer"""
    
    ENGINE_NAME = "divergence_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 4
    MIN_CANDLES = 60
    
    def get_neutral_state(self) -> Dict[str, Any]:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        rsi = CoreIndicators.calc_rsi_series(candles_df['close'], period=14)
        _, _, macd_hist = CoreIndicators.calc_macd_series(candles_df['close'])
        
        rsi_div, rsi_div_type = self._check_divergence(candles_df['close'], rsi)
        macd_div, macd_div_type = self._check_divergence(candles_df['close'], macd_hist)
        
        # Overall divergence
        divergence_detected = rsi_div or macd_div
        
        # Determine type (prioritize agreement)
        div_type = 'NONE'
        if rsi_div_type == macd_div_type and rsi_div_type != 'NONE':
            div_type = rsi_div_type  # Both agree - strong
        elif rsi_div:
            div_type = rsi_div_type
        elif macd_div:
            div_type = macd_div_type
        
        strength = self._divergence_strength(rsi_div, macd_div, rsi_div_type, macd_div_type)
        
        return {
            'divergence_detected': bool(divergence_detected),
            'divergence_type': div_type,
            'rsi_divergence': bool(rsi_div),
            'macd_divergence': bool(macd_div),
            'divergence_strength': strength,
            'both_confirm': bool(rsi_div and macd_div and rsi_div_type == macd_div_type),
            'confidence': 70 if divergence_detected else 60,
        }
    
    def _check_divergence(self, prices, indicator):
        """
        Compare price swings vs indicator swings.
        Bullish div: price lower low, indicator higher low.
        Bearish div: price higher high, indicator lower high.
        """
        try:
            p = prices.tail(40).reset_index(drop=True)
            ind = indicator.tail(40).reset_index(drop=True)
            
            if ind.isna().all():
                return False, 'NONE'
            
            # Find two recent swing points (split into halves)
            mid = len(p) // 2
            
            p_first_low = p[:mid].min()
            p_second_low = p[mid:].min()
            p_first_high = p[:mid].max()
            p_second_high = p[mid:].max()
            
            ind_first_low = ind[:mid].min()
            ind_second_low = ind[mid:].min()
            ind_first_high = ind[:mid].max()
            ind_second_high = ind[mid:].max()
            
            # Bullish divergence
            if p_second_low < p_first_low and ind_second_low > ind_first_low:
                return True, 'BULLISH'
            
            # Bearish divergence
            if p_second_high > p_first_high and ind_second_high < ind_first_high:
                return True, 'BEARISH'
            
            return False, 'NONE'
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _divergence_strength(self, rsi_div, macd_div, rsi_type, macd_type) -> int:
        """Score 0-100 for divergence strength"""
        if rsi_div and macd_div and rsi_type == macd_type:
            return 90  # Both confirm
        elif rsi_div and macd_div:
            return 55  # Both detect but conflicting types
        elif rsi_div or macd_div:
            return 50  # Single indicator
        return 0
    
