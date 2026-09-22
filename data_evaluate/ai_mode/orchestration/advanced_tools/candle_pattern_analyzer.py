"""
TIER 3 - CANDLE PATTERN ANALYZER


Detects candlestick patterns: Engulfing, Hammer, Doji, etc.
"""

import pandas as pd
from typing import Dict, Any, List

from data_evaluate.orchestration.base_engine import BaseEngine


class CandlePatternAnalyzer(BaseEngine):
    """Tier 3: Candle Pattern Analyzer"""
    
    ENGINE_NAME = "candle_pattern_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 3
    MIN_CANDLES = 10
    
    def get_neutral_state(self) -> Dict[str, Any]:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        if not isinstance(candles_df, pd.DataFrame):
            raise TypeError(f"candles_df must be a pandas DataFrame, got {type(candles_df)}")
        
        required_cols = {'open', 'high', 'low', 'close'}
        if candles_df.empty or len(candles_df) < self.MIN_CANDLES or not required_cols.issubset(candles_df.columns):
            raise ValueError("FAIL-FAST: Neutral state removed")

        patterns_detected = []
        
        # Check various patterns
        if self._is_bullish_engulfing(candles_df):
            patterns_detected.append('BULLISH_ENGULFING')
        if self._is_bearish_engulfing(candles_df):
            patterns_detected.append('BEARISH_ENGULFING')
        if self._is_hammer(candles_df):
            patterns_detected.append('HAMMER')
        if self._is_shooting_star(candles_df):
            patterns_detected.append('SHOOTING_STAR')
        if self._is_doji(candles_df):
            patterns_detected.append('DOJI')
        if self._is_morning_star(candles_df):
            patterns_detected.append('MORNING_STAR')
        if self._is_evening_star(candles_df):
            patterns_detected.append('EVENING_STAR')
        
        bias = self._determine_bias(patterns_detected)
        strength = len(patterns_detected) * 20
        
        return {
            'patterns_detected': patterns_detected,
            'pattern_count': len(patterns_detected),
            'pattern_strength': min(100, strength),
            'bias': bias,
            'last_candle_color': 'BULLISH' if candles_df['close'].iloc[-1] > candles_df['open'].iloc[-1] else 'BEARISH',
            'confidence': min(90, 40 + strength),
        }
    
    def _is_bullish_engulfing(self, df) -> bool:
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        return (prev['close'] < prev['open'] and  # Previous bearish
                curr['close'] > curr['open'] and  # Current bullish
                curr['open'] < prev['close'] and  # Opens below prev close
                curr['close'] > prev['open'])     # Closes above prev open
    
    def _is_bearish_engulfing(self, df) -> bool:
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        return (prev['close'] > prev['open'] and
                curr['close'] < curr['open'] and
                curr['open'] > prev['close'] and
                curr['close'] < prev['open'])
    
    def _is_hammer(self, df) -> bool:
        c = df.iloc[-1]
        body = abs(c['close'] - c['open'])
        lower_wick = min(c['open'], c['close']) - c['low']
        upper_wick = c['high'] - max(c['open'], c['close'])
        total = c['high'] - c['low']
        if total == 0:
            return False
        return (lower_wick > body * 2 and
                upper_wick < body * 0.5 and
                body / total > 0.1)
    
    def _is_shooting_star(self, df) -> bool:
        c = df.iloc[-1]
        body = abs(c['close'] - c['open'])
        lower_wick = min(c['open'], c['close']) - c['low']
        upper_wick = c['high'] - max(c['open'], c['close'])
        total = c['high'] - c['low']
        if total == 0:
            return False
        return (upper_wick > body * 2 and
                lower_wick < body * 0.5 and
                body / total > 0.1)
    
    def _is_doji(self, df) -> bool:
        c = df.iloc[-1]
        body = abs(c['close'] - c['open'])
        total = c['high'] - c['low']
        if total == 0:
            return False
        return body / total < 0.1
    
    def _is_morning_star(self, df) -> bool:
        c1 = df.iloc[-3]
        c2 = df.iloc[-2]
        c3 = df.iloc[-1]
        return (c1['close'] < c1['open'] and  # First bearish
                abs(c2['close'] - c2['open']) < abs(c1['close'] - c1['open']) * 0.5 and  # Small body
                c3['close'] > c3['open'] and  # Third bullish
                c3['close'] > (c1['open'] + c1['close']) / 2)  # Closes above midpoint
    
    def _is_evening_star(self, df) -> bool:
        c1 = df.iloc[-3]
        c2 = df.iloc[-2]
        c3 = df.iloc[-1]
        return (c1['close'] > c1['open'] and
                abs(c2['close'] - c2['open']) < abs(c1['close'] - c1['open']) * 0.5 and
                c3['close'] < c3['open'] and
                c3['close'] < (c1['open'] + c1['close']) / 2)
    
    def _determine_bias(self, patterns: List[str]) -> str:
        bullish = ['BULLISH_ENGULFING', 'HAMMER', 'MORNING_STAR']
        bearish = ['BEARISH_ENGULFING', 'SHOOTING_STAR', 'EVENING_STAR']
        
        bull_count = sum(1 for p in patterns if p in bullish)
        bear_count = sum(1 for p in patterns if p in bearish)
        
        if bull_count > bear_count:
            return 'BULLISH'
        elif bear_count > bull_count:
            return 'BEARISH'
        return 'NEUTRAL'
    
