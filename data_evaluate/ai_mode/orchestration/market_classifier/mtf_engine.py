"""
TIER 1 - MTF (Multi-Timeframe) ENGINE


Analyzes multiple timeframes to detect alignment or conflict.
Critical for binary options to confirm setup across timeframes.
"""

import pandas as pd
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class MTFEngine(BaseEngine):
    """Tier 1: Multi-Timeframe Engine"""
    
    ENGINE_NAME = "mtf_engine"
    ENGINE_VERSION = "1.0.0"
    TIER = 1
    MIN_CANDLES = 50
    
    def analyze(self, payload: Dict[str, Any], candles_dict: Dict[str, pd.DataFrame] = None, **kwargs) -> Dict[str, Any]:
        """MTF analyzes across timeframes"""
        try:
            # Zero Tolerance validation
            if not candles_dict:
                raise ValueError("FAIL-FAST: Missing candles_dict for MTF analysis")
                
            # Validate each timeframe
            required_timeframes = ['M1', 'M5', 'M15']
            for tf in required_timeframes:
                if tf not in candles_dict:
                    raise ValueError(f"FAIL-FAST: Missing required timeframe {tf} in candles_dict")
                if candles_dict[tf] is None or candles_dict[tf].empty:
                    raise ValueError(f"FAIL-FAST: Invalid {tf} data in candles_dict")
                if len(candles_dict[tf]) < 50:
                    raise ValueError(f"FAIL-FAST: Insufficient {tf} candles (minimum 50 required)")
            
            directions = {}
            for tf, df in candles_dict.items():
                if df is None or len(df) < 50:
                    raise ValueError(f"FAIL-FAST: Invalid {tf} data - insufficient candles")
                # Pass timeframe payload to _tf_direction for SSOT compliance
                tf_key = tf.lower()
                tf_payload = payload.get(tf_key, {})
                directions[tf] = self._tf_direction(df, tf_payload)
            
            if not directions:
                raise ValueError("FAIL-FAST: No valid timeframe directions detected")
            
            # Calculate alignment
            up_count = sum(1 for d in directions.values() if d == 'UP')
            down_count = sum(1 for d in directions.values() if d == 'DOWN')
            total = len(directions)
            
            # Alignment score
            max_count = max(up_count, down_count)
            alignment_score = int((max_count / total) * 100) if total > 0 else 50
            
            # Dominant direction
            if up_count > down_count:
                dominant = 'UP'
            elif down_count > up_count:
                dominant = 'DOWN'
            else:
                dominant = 'NONE'
            
            # HTF direction (highest available timeframe)
            tf_order = ['D1', 'H4', 'H1', 'M60', 'M30', 'M15', 'M5', 'M1']
            htf_direction = 'NONE'
            for tf in tf_order:
                if tf in directions:
                    htf_direction = directions[tf]
                    break
            
            # LTF direction (lowest available)
            ltf_direction = 'NONE'
            for tf in reversed(tf_order):
                if tf in directions:
                    ltf_direction = directions[tf]
                    break
            
            # Conflict detection
            htf_ltf_conflict = (
                htf_direction != 'NONE' and 
                ltf_direction != 'NONE' and
                htf_direction != ltf_direction
            )
            
            return {
                'directions_by_tf': directions,
                'alignment_score': alignment_score,
                'dominant_direction': dominant,
                'htf_direction': htf_direction,
                'ltf_direction': ltf_direction,
                'htf_ltf_conflict': htf_ltf_conflict,
                'timeframes_analyzed': list(directions.keys()),
                'confidence_from_mtf': alignment_score,
                'confidence': alignment_score,
            }
        except Exception as e:
            raise
    
    def _tf_direction(self, df: pd.DataFrame, payload_tf: Dict[str, Any] = None) -> str:
        """Quick direction check for single timeframe using pre-computed SSOT values"""
        try:
            close = df['close'].iloc[-1]
            # Use pre-computed values from payload (SSOT)
            if not payload_tf or 'ema20' not in payload_tf or 'ema50' not in payload_tf:
                raise ValueError("FAIL-FAST: Missing ema20/ema50 in payload_tf for MTFEngine")
            
            ema20 = payload_tf['ema20']
            ema50 = payload_tf['ema50']
            
            if close > ema20 > ema50:
                return 'UP'
            elif close < ema20 < ema50:
                return 'DOWN'
            return 'NONE'
        except Exception as e:
            raise
    
