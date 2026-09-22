"""
TIER 5 - CONTINUATION ANALYZER


Estimates probability that the current move will continue vs reverse.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple

from data_evaluate.strategies_mode.orchestration.base_engine import BaseEngine


class ContinuationAnalyzer(BaseEngine):
    """Tier 5: Move Continuation Analyzer"""
    
    ENGINE_NAME = "continuation_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 5
    MIN_CANDLES = 50
    
    def get_neutral_state(self) -> Dict[str, Any]:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        payload = kwargs.get('basic_payload') or kwargs.get('payload') or {}
        m5 = payload.get('m5', {}) if isinstance(payload, dict) else {}

        pullback_health = self._assess_pullback(candles_df, m5)
        momentum_intact = self._momentum_intact(candles_df)
        volume_support = self._volume_support(candles_df)
        
        continuation_prob = self._calculate_continuation_probability(
            pullback_health, momentum_intact, volume_support, candles_df
        )
        reversal_prob = 100 - continuation_prob
        
        retest_detected, retest_quality, retest_type = self._analyze_retest(candles_df)
        
        # If a healthy retest is confirmed, boost continuation probability!
        if retest_detected:
            continuation_prob = min(98, continuation_prob + 15)
            reversal_prob = 100 - continuation_prob
        
        return {
            'continuation_probability': continuation_prob,
            'reversal_probability': reversal_prob,
            'pullback_health': pullback_health,
            'momentum_intact': bool(momentum_intact),
            'volume_supports_move': bool(volume_support),
            'bias': 'CONTINUATION' if continuation_prob > 55 else (
                    'REVERSAL' if continuation_prob < 45 else 'NEUTRAL'),
            'confidence': 70,
            
            # Enhancement 3: Retest Analyzer metrics
            'retest_detected': retest_detected,
            'retest_quality': retest_quality,
            'retest_type': retest_type,
        }
        
    def _analyze_retest(self, df: pd.DataFrame) -> Tuple[bool, float, str]:
        """
        Enhancement 3: Retest Analyzer.
        Detects if price has broken out of a support/resistance level,
        then yetted (retested) that level and got rejected.
        """
        try:
            closes = df['close'].tail(30).values
            highs = df['high'].tail(30).values
            lows = df['low'].tail(30).values
            
            # Identify a support and resistance level in the tail (excluding recent candles)
            ref_high = max(highs[:-5])
            ref_low = min(lows[:-5])
            
            retest_detected = False
            retest_quality = 0.0
            retest_type = 'NONE'
            
            # Check for BULLISH retest: broke above ref_high, then touched/approached it and bounced
            last_close = closes[-1]
            last_low = lows[-1]
            
            # Broke out in last 5 candles
            broke_high = any(closes[i] > ref_high for i in range(-5, -1))
            if broke_high and last_close > ref_high:
                # Retested the broken level (low got close to it)
                distance_to_high = abs(last_low - ref_high) / ref_high
                if distance_to_high < 0.002: # touched or almost touched
                    retest_detected = True
                    retest_type = 'BULLISH'
                    # Quality is higher if close is higher than open (rejection)
                    retest_quality = 85.0 if closes[-1] > df['open'].iloc[-1] else 60.0
                    
            # Check for BEARISH retest: broke below ref_low, then touched/approached it and bounced down
            broke_low = any(closes[i] < ref_low for i in range(-5, -1))
            if broke_low and last_close < ref_low:
                # Retested the broken level (high got close to it)
                distance_to_low = abs(highs[-1] - ref_low) / ref_low
                if distance_to_low < 0.002:
                    retest_detected = True
                    retest_type = 'BEARISH'
                    retest_quality = 85.0 if closes[-1] < df['open'].iloc[-1] else 60.0
                    
            return retest_detected, retest_quality, retest_type
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _assess_pullback(self, df: pd.DataFrame, m5: Dict[str, Any] = None) -> int:
        """Assess if recent pullback is healthy (0-100)"""
        try:
            last_close = df['close'].iloc[-1]
            
            if not m5 or 'ema20' not in m5 or m5['ema20'] is None:
                raise ValueError("FAIL-FAST: Missing ema20 in payload for continuation_analyzer")
            last_ema = m5['ema20']
            
            if last_ema == 0:
                return 50
            
            distance = abs(last_close - last_ema) / last_ema
            
            # Healthy pullback: close to EMA (not overextended)
            if distance < 0.005:
                return 80  # Near EMA = healthy
            elif distance < 0.015:
                return 60
            elif distance < 0.03:
                return 40
            else:
                return 20  # Overextended
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _momentum_intact(self, df) -> bool:
        """Is momentum still supporting the move?"""
        try:
            closes = df['close']
            
            # Recent vs older momentum
            c_7 = closes.iloc[-7] if closes.iloc[-7] != 0 else 1e-6
            c_14 = closes.iloc[-14] if closes.iloc[-14] != 0 else 1e-6
            recent_roc = (closes.iloc[-1] - c_7) / c_7 * 100
            older_roc = (c_7 - c_14) / c_14 * 100
            
            # Momentum intact if same direction
            return np.sign(recent_roc) == np.sign(older_roc) and abs(recent_roc) > 0.1
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _volume_support(self, df) -> bool:
        """Does volume support the move?"""
        try:
            if 'volume' not in df.columns or df['volume'].sum() == 0:
                return True  # Neutral default for OTC or missing volume

            recent_vol = df['volume'].tail(10).mean()
            past_vol = df['volume'].tail(30).mean()

            # Volume supports if recent >= past
            return recent_vol >= past_vol * 0.8
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _calculate_continuation_probability(self, pullback, momentum, 
                                           volume, df) -> int:
        """Continuation probability 0-100"""
        prob = 50
        
        # Pullback health
        prob += (pullback - 50) * 0.3
        
        # Momentum
        if momentum:
            prob += 15
        else:
            prob -= 12
        
        # Volume
        if volume:
            prob += 8
        else:
            prob -= 8
        
        # Trend strength check
        try:
            closes = df['close'].tail(20)
            slope = np.polyfit(np.arange(len(closes)), closes.values, 1)[0]
            if abs(slope) > 0.0005:
                prob += 10
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
        
        return int(min(95, max(5, prob)))
    
