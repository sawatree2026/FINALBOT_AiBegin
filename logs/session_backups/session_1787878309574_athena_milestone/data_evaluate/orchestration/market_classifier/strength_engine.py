"""
TIER 1 - STRENGTH ENGINE


Measure momentum strength using ADX, RSI, MACD, and Rate of Change.
Detects divergence between price and momentum indicators.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

from data_evaluate.orchestration.base_engine import BaseEngine


class StrengthEngine(BaseEngine):
    """Tier 1: Momentum Strength Engine"""
    
    ENGINE_NAME = "strength_engine"
    ENGINE_VERSION = "1.0.0"
    TIER = 1
    MIN_CANDLES = 200
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, payload: Dict[str, Any], candles_dict: Dict[str, pd.DataFrame] = None, **kwargs) -> Dict[str, Any]:
        """Analyze momentum strength using SSOT payload"""
        m5 = payload['m5']
        if not m5:
            raise ValueError("FAIL-FAST: Neutral state removed")
        if not candles_dict:
            raise ValueError("FAIL-FAST: Missing candles_dict for strength analysis")
        if 'M5' not in candles_dict or candles_dict['M5'] is None or candles_dict['M5'].empty:
            raise ValueError("FAIL-FAST: Invalid M5 data in candles_dict")
        if len(candles_dict['M5']) < 50:
            raise ValueError("FAIL-FAST: Insufficient M5 candles (minimum 50 required)")
            
        # Validate required indicator fields
        required_fields = ['adx', 'di_plus', 'di_minus', 'rsi14', 'macd', 'macd_hist', 'roc']
        for field in required_fields:
            if field not in m5 or m5[field] is None:
                raise ValueError(f"FAIL-FAST: Missing required field in m5: {field}")
            
        adx_val = m5['adx']
        di_plus = m5['di_plus']
        di_minus = m5['di_minus']
        rsi_val = m5['rsi14']
        macd_val = m5['macd']
        macd_hist = m5['macd_hist']
        roc_val = m5['roc']
        
        momentum_level = self._classify_momentum_level(adx_val)
        divergence = self._detect_divergence(roc_val, rsi_val, macd_hist)
        strength_score = self._calculate_strength_score(adx_val, rsi_val, abs(macd_val), abs(roc_val))
        exhaustion_risk = self._calculate_exhaustion_risk(adx_val, rsi_val, macd_val, roc_val)
        
        return {
            'adx': float(adx_val),
            'di_plus': float(di_plus),
            'di_minus': float(di_minus),
            'rsi': float(rsi_val),
            'macd': float(macd_val),
            'momentum_level': momentum_level,
            'roc': float(roc_val),
            'divergence': divergence,
            'strength_score': strength_score,
            'exhaustion_risk': exhaustion_risk,
            'confidence': min(100, strength_score + 10),  # Add for compatibility
        }
    

    
    def _classify_momentum_level(self, adx: float) -> str:
        if adx > 50: return 'EXTREME'
        elif adx > 35: return 'STRONG'
        elif adx > 20: return 'NORMAL'
        return 'WEAK'
    
    def _detect_divergence(self, roc_val: float, rsi: float, macd_hist: float) -> str:
        try:
            price_trend = roc_val > 0
            rsi_up = rsi > 50
            macd_up = macd_hist > 0
            momentum_up = rsi_up and macd_up
            
            if price_trend and not momentum_up:
                return 'BEARISH'
            elif not price_trend and momentum_up:
                return 'BULLISH'
            return 'NONE'
        except Exception as e:
            raise
    
    def _calculate_strength_score(self, adx, rsi, macd_abs, roc_abs) -> int:
        score = 50
        if adx > 40: score += 20
        elif adx > 25: score += 15
        elif adx > 20: score += 10
        if rsi > 70 or rsi < 30: score += 10
        elif rsi > 60 or rsi < 40: score += 5
        if macd_abs > 1.0: score += 10
        elif macd_abs > 0.5: score += 5
        if roc_abs > 3.0: score += 8
        elif roc_abs > 1.5: score += 4
        return min(100, max(20, score))
    
    def _calculate_exhaustion_risk(self, adx, rsi, macd_val, roc_val) -> int:
        risk = 30
        if adx > 50: risk += 20
        elif adx > 40: risk += 10
        if rsi > 80 or rsi < 20: risk += 15
        try:
            if macd_val < 0 and roc_val > 0:
                risk += 10
        except Exception as e:
            raise
        return min(100, max(10, risk))
    
