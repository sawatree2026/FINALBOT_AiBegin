"""
TIER 5 - EFFICIENCY ANALYZER


Measures how efficiently price moves (directness of moves).
High efficiency = clean trend. Low efficiency = choppy.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class EfficiencyAnalyzer(BaseEngine):
    """Tier 5: Price Efficiency Analyzer"""
    
    ENGINE_NAME = "efficiency_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 5
    MIN_CANDLES = 40
    
    def get_neutral_state(self) -> Dict[str, Any]:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        # Kaufman Efficiency Ratio
        efficiency_ratio = self._kaufman_efficiency(candles_df, period=20)
        
        # Path efficiency
        path_efficiency = self._path_efficiency(candles_df)
        
        # Directional efficiency
        directional = self._directional_efficiency(candles_df)
        
        overall = int((efficiency_ratio + path_efficiency + directional) / 3)
        
        return {
            'efficiency_ratio': float(efficiency_ratio),
            'path_efficiency': float(path_efficiency),
            'directional_efficiency': float(directional),
            'overall_efficiency': overall,
            'movement_quality': self._classify_quality(overall),
            'is_efficient': overall > 60,
            'confidence': 75,
        }
    
    def _kaufman_efficiency(self, df, period=20) -> float:
        """Kaufman Efficiency Ratio (0-100)"""
        try:
            closes = df['close'].tail(period + 1)
            
            # Net change
            net_change = abs(closes.iloc[-1] - closes.iloc[0])
            
            # Sum of absolute changes
            total_change = closes.diff().abs().sum()
            
            if total_change == 0:
                return 50.0
            
            er = (net_change / total_change) * 100
            return float(min(100, er))
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _path_efficiency(self, df) -> float:
        """How direct is the price path (0-100)"""
        try:
            recent = df.tail(20)
            
            # Straight-line distance
            start = recent['close'].iloc[0]
            end = recent['close'].iloc[-1]
            straight = abs(end - start)
            
            # Actual path (sum of ranges)
            actual = (recent['high'] - recent['low']).sum()
            
            if actual == 0:
                return 50.0
            
            return float(min(100, (straight / actual) * 100))
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _directional_efficiency(self, df) -> float:
        """Ratio of candles moving in dominant direction"""
        try:
            recent = df.tail(20)
            bullish = (recent['close'] > recent['open']).sum()
            bearish = (recent['close'] < recent['open']).sum()
            total = len(recent)
            
            if total == 0:
                return 50.0
            
            dominant = max(bullish, bearish)
            return float((dominant / total) * 100)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _classify_quality(self, efficiency: int) -> str:
        if efficiency > 75:
            return 'EXCELLENT'
        elif efficiency > 55:
            return 'GOOD'
        elif efficiency > 35:
            return 'FAIR'
        return 'POOR'
    
