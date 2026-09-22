"""
TIER 5 - MARKET PRESSURE ANALYZER (Orderflow Proxy)


Estimates buying vs selling pressure using candle structure and volume.
A proxy for orderflow when actual orderbook data is unavailable.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class MarketPressureAnalyzer(BaseEngine):
    """Tier 5: Market Pressure / Orderflow Analyzer"""
    
    ENGINE_NAME = "market_pressure_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 5
    MIN_CANDLES = 40
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        buy_pressure = self._calculate_buy_pressure(candles_df)
        sell_pressure = 100 - buy_pressure
        
        absorption = self._detect_absorption(candles_df)
        effort_result = self._effort_vs_result(candles_df)
        
        dominant = 'BUYERS' if buy_pressure > 55 else (
                   'SELLERS' if buy_pressure < 45 else 'BALANCED')
        
        return {
            'buy_pressure': buy_pressure,
            'sell_pressure': sell_pressure,
            'dominant_side': dominant,
            'absorption_detected': bool(absorption),
            'effort_vs_result': effort_result,
            'pressure_imbalance': abs(buy_pressure - 50) * 2,
            'confidence': 65,
        }
    
    def _calculate_buy_pressure(self, df) -> int:
        """Estimate buying pressure 0-100"""
        try:
            recent = df.tail(20)
            
            buy_score = 0
            total_weight = 0
            
            for _, candle in recent.iterrows():
                rng = candle['high'] - candle['low']
                if rng == 0:
                    continue
                
                # Close position within range (high close = buying)
                close_position = (candle['close'] - candle['low']) / rng
                
                # Weight by volume if available
                weight = candle['volume']
                
                buy_score += close_position * weight
                total_weight += weight
            
            if total_weight == 0:
                return 50
            
            return int((buy_score / total_weight) * 100)
        except Exception as e:
            raise
    
    def _detect_absorption(self, df) -> bool:
        """Detect absorption: high volume but little price movement"""
        try:
            if 'volume' not in df.columns:
                return False
            
            recent = df.tail(10)
            
            for _, candle in recent.iterrows():
                rng = candle['high'] - candle['low']
                body = abs(candle['close'] - candle['open'])
                vol = candle['volume']
                
                avg_vol = recent['volume'].mean()
                avg_range = (recent['high'] - recent['low']).mean()
                
                # High volume + small range = absorption
                if vol > avg_vol * 1.5 and rng < avg_range * 0.7:
                    return True
            
            return False
        except Exception as e:
            raise
    
    def _effort_vs_result(self, df) -> str:
        """Compare effort (volume) vs result (price move)"""
        try:
            if 'volume' not in df.columns:
                raise ValueError("DataFrame must contain 'volume' column")
            
            recent = df.tail(10)
            
            avg_vol = recent['volume'].mean()
            # Calculate cumulative path instead of net A to B
            path_move = abs(recent['close'].diff()).sum()
            avg_price = recent['close'].mean()
            
            if avg_price == 0:
                raise ValueError("Average price cannot be zero")
            
            move_pct = path_move / avg_price * 100
            
            # High volume + low cumulative move = effort without result (choppy absorption)
            if avg_vol > 0 and move_pct < 0.2:
                return 'EFFORT_NO_RESULT'
            elif move_pct > 1.0:
                return 'STRONG_RESULT'
            else:
                return 'NORMAL'
        except Exception as e:
            raise
    
