"""
TIER 1 - TREND ENGINE


Detects price direction, trend strength, momentum type, and reversal risk.
Uses: EMA (20/50/100/200), slope calculation, candle momentum.
Calibrated with dynamic scaling for Forex and large assets.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class TrendEngine(BaseEngine):
    """Tier 1: Trend Intelligence Engine"""
    
    ENGINE_NAME = "trend_engine"
    ENGINE_VERSION = "1.0.1"
    TIER = 1
    MIN_CANDLES = 200
    
    def _get_thresholds(self, latest_price: float) -> Dict[str, float]:
        if latest_price < 5.0: # Forex (EURUSD ~ 1.08)
            return {
                'slope_impulsive': 0.00006,
                'slope_corrective_min': 0.00002,
                'slope_corrective_max': 0.00006,
                'momentum_impulsive': 0.10,
                'momentum_corrective_min': 0.02,
                'momentum_corrective_max': 0.15,
                
                'strength_100': 0.0001,
                'strength_80': 0.00005,
                'strength_60': 0.00003,
                'strength_40': 0.00001,
                
                'conf_slope_large': 0.0001,
                'conf_slope_med': 0.00005,
                'conf_mom_large': 0.15,
                'conf_mom_med': 0.08,
            }
        else: # Large assets like Crypto / Stocks / Indices
            return {
                'slope_impulsive': 0.0005,
                'slope_corrective_min': 0.0001,
                'slope_corrective_max': 0.0005,
                'momentum_impulsive': 1.0,
                'momentum_corrective_min': 0.2,
                'momentum_corrective_max': 1.5,
                
                'strength_100': 0.002,
                'strength_80': 0.001,
                'strength_60': 0.00005,
                'strength_40': 0.0001,
                
                'conf_slope_large': 0.001,
                'conf_slope_med': 0.0005,
                'conf_mom_large': 2.0,
                'conf_mom_med': 1.0,
            }
            
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, payload: Dict[str, Any], candles_dict: Dict[str, pd.DataFrame] = None, **kwargs) -> Dict[str, Any]:
        """Analyze trend using pre-calculated SSOT payload"""
        m5 = payload['m5']
        latest_price = payload['ohlcv']['m1_close']
        
        # Validate data completeness - Zero Tolerance
        if not m5 or latest_price == 0.0:
            raise ValueError("FAIL-FAST: Invalid trend data - missing m5 or zero price")
        if not candles_dict:
            raise ValueError("FAIL-FAST: Missing candles_dict for trend analysis")
        if 'M5' not in candles_dict or candles_dict['M5'] is None or candles_dict['M5'].empty:
            raise ValueError("FAIL-FAST: Invalid M5 data in candles_dict")
        if len(candles_dict['M5']) < 50:
            raise ValueError("FAIL-FAST: Insufficient M5 candles (minimum 50 required)")
            
        # Validate required indicator fields
        required_fields = ['ema20', 'ema50', 'ema100', 'ema200', 'slope_10', 'roc']
        for field in required_fields:
            if field not in m5 or m5[field] is None:
                raise ValueError(f"FAIL-FAST: Missing required field in m5: {field}")
            
        thresholds = self._get_thresholds(latest_price)
        
        ema20 = m5['ema20']
        ema50 = m5['ema50']
        ema100 = m5['ema100']
        ema200 = m5['ema200']
        
        # Direction
        direction = self._determine_direction(
            price=latest_price,
            ema20=ema20,
            ema50=ema50,
            ema100=ema100,
            ema200=ema200,
        )
        
        # Get slope and momentum directly from SSOT
        slope = m5['slope_10']
        momentum = m5['roc']
        
        # Determine trend type
        trend_type = self._analyze_trend_type(slope, momentum, direction, thresholds)
        
        # Calculate confidence
        confidence = self._score_confidence(direction, slope, ema20, momentum, latest_price, thresholds)
        
        # Reversal risk
        reversal_risk = self._calculate_reversal_risk(direction, slope, ema20, latest_price)
        
        # Sustain probability
        sustain_probability = self._calculate_sustain_probability(
            direction, slope, momentum, thresholds
        )
        
        return {
            'direction': direction,
            'strength': self._slope_to_strength(direction, slope, thresholds),
            'slope': float(slope),
            'momentum': float(momentum),
            'type': trend_type,
            'confidence': confidence,
            'reversal_risk': reversal_risk,
            'sustain_probability': sustain_probability,
        }
    
    def _determine_direction(self, price, ema20, ema50, ema100, ema200) -> str:
        if price > ema20 > ema50 > ema100:
            return 'UP'
        elif price < ema20 < ema50 < ema100:
            return 'DOWN'
        return 'NONE'
    

    
    def _analyze_trend_type(self, slope, momentum, direction, thresholds) -> str:
        if direction == 'NONE':
            return 'CHOPPY'
        abs_slope = abs(slope)
        abs_momentum = abs(momentum)
        if abs_slope > thresholds['slope_impulsive'] and abs_momentum > thresholds['momentum_impulsive']:
            return 'IMPULSIVE'
        elif (thresholds['slope_corrective_min'] <= abs_slope <= thresholds['slope_corrective_max']) and \
             (thresholds['momentum_corrective_min'] <= abs_momentum <= thresholds['momentum_corrective_max']):
            return 'CORRECTIVE'
        return 'CHOPPY'
    
    def _score_confidence(self, direction, slope, ema20, momentum, latest_price, thresholds) -> int:
        if direction == 'NONE':
            return 20
        score = 50
        abs_slope = abs(slope)
        if abs_slope > thresholds['conf_slope_large']:
            score += 20
        elif abs_slope > thresholds['conf_slope_med']:
            score += 10
        abs_momentum = abs(momentum)
        if abs_momentum > thresholds['conf_mom_large']:
            score += 15
        elif abs_momentum > thresholds['conf_mom_med']:
            score += 10
        
        if ema20 != 0:
            distance = abs(latest_price - ema20) / abs(latest_price)
            if distance < 0.01:
                score += 5
        return min(100, max(20, score))
    
    def _calculate_reversal_risk(self, direction, slope, ema20, latest_price) -> int:
        if direction == 'NONE':
            return 50
        risk = 30
        try:
            # We no longer have full df to calculate older_slope, so we rely on price extension from EMA
            if ema20 != 0:
                distance = abs(latest_price - ema20) / abs(ema20)
                if distance > 0.02:
                    risk += 25
                elif distance > 0.01:
                    risk += 15
        except Exception as e:
            raise
        return min(100, max(10, risk))
    
    def _calculate_sustain_probability(self, direction, slope, momentum, thresholds) -> int:
        if direction == 'NONE':
            return 30
        prob = 50
        abs_slope = abs(slope)
        if abs_slope > thresholds['conf_slope_large']:
            prob += 25
        elif abs_slope > thresholds['conf_slope_med']:
            prob += 15
        abs_momentum = abs(momentum)
        if abs_momentum > thresholds['conf_mom_large']:
            prob += 20
        elif abs_momentum > thresholds['conf_mom_med']:
            prob += 10
        return min(100, max(20, prob))
    
    def _slope_to_strength(self, direction, slope, thresholds) -> int:
        if direction == 'NONE':
            return 20
        abs_slope = abs(slope)
        if abs_slope > thresholds['strength_100']:
            return 100
        elif abs_slope > thresholds['strength_80']:
            return 80
        elif abs_slope > thresholds['strength_60']:
            return 60
        elif abs_slope > thresholds['strength_40']:
            return 40
        return 20
    
