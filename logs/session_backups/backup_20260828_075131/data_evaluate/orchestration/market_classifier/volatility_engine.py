"""
TIER 1 - VOLATILITY ENGINE


Measure market volatility using ATR, Bollinger Bands, and historical percentile.
Classify volatility regime and detect compression/expansion.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

from data_evaluate.orchestration.base_engine import BaseEngine


class VolatilityEngine(BaseEngine):
    """Tier 1: Volatility Engine"""
    
    ENGINE_NAME = "volatility_engine"
    ENGINE_VERSION = "1.0.0"
    TIER = 1
    MIN_CANDLES = 200
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, payload: Dict[str, Any], candles_dict: Dict[str, pd.DataFrame] = None, **kwargs) -> Dict[str, Any]:
        m5 = payload['m5']
        if not m5:
            raise ValueError("FAIL-FAST: Neutral state removed")
        if not candles_dict:
            raise ValueError("FAIL-FAST: Missing candles_dict for volatility analysis")
        if 'M5' not in candles_dict or candles_dict['M5'] is None or candles_dict['M5'].empty:
            raise ValueError("FAIL-FAST: Invalid M5 data in candles_dict")
        if len(candles_dict['M5']) < 50:
            raise ValueError("FAIL-FAST: Insufficient M5 candles (minimum 50 required)")
            
        # Validate required indicator fields
        required_fields = ['atr14', 'atr_percentile', 'atr_zscore', 'bb_width', 'bbw_sma_100']
        for field in required_fields:
            if field not in m5 or m5[field] is None:
                raise ValueError(f"FAIL-FAST: Missing required field in m5: {field}")
                
        # Validate payload structure
        if 'price_action' not in payload:
            raise ValueError("FAIL-FAST: Missing price_action in payload")
        if 'ohlcv' not in payload:
            raise ValueError("FAIL-FAST: Missing ohlcv in payload")
            
        atr_val = m5['atr14']
        atr_percentile = m5['atr_percentile']
        zscore = m5['atr_zscore']
        bbw = m5['bb_width']
        bbw_sma_100 = m5['bbw_sma_100']
        
        # Estimate stddev from bbw (BB has 2 stddev multiplier, so bbw = 4 stddev => stddev = bbw/4)
        stddev = bbw / 4.0 if bbw > 0 else 0.0
        
        regime = self._classify_regime(atr_percentile)
        
        # Pass the recent highs/lows range from price_action if available, else estimate
        pa = payload['price_action']
        
        volatility_score = self._calculate_volatility_score(
            atr_percentile, bbw, stddev, payload['ohlcv']['m1_close']
        )
        
        expansion_prob, contraction_prob = self._detect_expansion_contraction(
            m5['atr_recent_avg'], m5['atr_past_avg']
        )
        
        spike_detected = abs(zscore) > 2.0
        
        bbw_ratio, compression_quality = self._calculate_compression_quality(
            atr_percentile, bbw, bbw_sma_100
        )
        
        return {
            'atr': float(atr_val),
            'atr_percentile': float(atr_percentile),
            'bbw': float(bbw),
            'stddev': float(stddev),
            'regime': regime,
            'volatility_score': volatility_score,
            'expansion_probability': expansion_prob,
            'contraction_probability': contraction_prob,
            'volatility_zscore': float(zscore),
            'spike_detected': bool(spike_detected),
            'confidence': self._calculate_confidence(atr_val, regime),
            
            # Enhancement 2: Compression metrics
            'bbw_compression_ratio': bbw_ratio,
            'compression_quality': compression_quality,
        }
        
    def _calculate_compression_quality(self, atr_pct: float, current_bbw: float, historical_bbw_sma: float) -> Tuple[float, float]:
        """Calculate Bollinger Bands squeeze ratio and Compression Squeeze Quality score using precomputed SSOT values"""
        try:
            if historical_bbw_sma == 0 or np.isnan(historical_bbw_sma):
                bbw_compression_ratio = 1.0
            else:
                bbw_compression_ratio = round(float(current_bbw / historical_bbw_sma), 4)
                
            # Compute quality 0-100: lower ratio & lower atr_pct = higher quality squeeze
            quality = 100.0
            if bbw_compression_ratio > 0.8:
                quality -= (bbw_compression_ratio - 0.8) * 100
            quality -= max(0.0, (atr_pct - 20.0) * 0.8)
            
            compression_quality = round(float(max(0.0, min(100.0, quality))), 2)
            return bbw_compression_ratio, compression_quality
        except Exception as e:
            raise
    
    def _classify_regime(self, atr_percentile) -> str:
        if atr_percentile > 75: return 'EXTREME'
        elif atr_percentile > 50: return 'HIGH'
        elif atr_percentile > 25: return 'NORMAL'
        return 'LOW'
    
    def _calculate_volatility_score(self, atr_percentile, bbw, stddev, latest_price) -> int:
        score = 50
        if atr_percentile > 75: score += 30
        elif atr_percentile > 50: score += 15
        if bbw > stddev * 4: score += 15
        elif bbw > stddev * 2: score += 8
        return min(100, max(20, score))
    
    def _detect_expansion_contraction(self, recent_avg: float, past_avg: float) -> Tuple[int, int]:
        try:
            if recent_avg == 0 or past_avg == 0:
                raise ValueError(f"ATR averages invalid: recent_avg={recent_avg}, past_avg={past_avg}")

            if recent_avg < past_avg:
                ratio = recent_avg / (past_avg + 0.00001)
                if ratio < 0.8:
                    return 70, 30
                return 55, 45
            return 40, 60
        except Exception as e:
            raise
    
    def _calculate_confidence(self, atr_val, regime) -> int:
        if regime == 'EXTREME': return 40  # Less reliable in extremes
        elif regime == 'LOW': return 65
        return 80  # Normal/High volatility = good info
    
