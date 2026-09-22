"""
TIER 5 - CONFLICT ANALYZER


Detects internal conflicts between signals/timeframes/indicators.
When signals conflict, confidence should drop.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List

from data_evaluate.strategies_mode.orchestration.base_engine import BaseEngine


class ConflictAnalyzer(BaseEngine):
    """Tier 5: Signal Conflict Analyzer"""
    
    ENGINE_NAME = "conflict_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 5
    MIN_CANDLES = 50
    
    def get_neutral_state(self) -> Dict[str, Any]:
        return {}

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        # Get payload from kwargs for pre-computed indicators
        payload = kwargs.get('basic_payload') or kwargs.get('payload') or {}
        m5 = payload.get('m5', {}) if isinstance(payload, dict) else {}
        
        # Multiple direction indicators - using pre-computed values from SSOT
        ema_direction = self._ema_direction(candles_df, m5)
        momentum_direction = self._momentum_direction(candles_df)
        candle_direction = self._candle_direction(candles_df)
        
        directions = [ema_direction, momentum_direction, candle_direction]
        valid_dirs = [d for d in directions if d != 'NONE']
        
        # Count conflicts
        conflicts = self._count_conflicts(valid_dirs)
        conflict_score = self._calculate_conflict_score(valid_dirs)
        
        # Agreement level
        if valid_dirs:
            up = valid_dirs.count('UP')
            down = valid_dirs.count('DOWN')
            agreement = max(up, down) / len(valid_dirs) * 100
        else:
            agreement = 50
        
        return {
            'conflict_detected': conflict_score > 50,
            'conflict_score': conflict_score,
            'agreement_score': int(agreement),
            'ema_direction': ema_direction,
            'momentum_direction': momentum_direction,
            'candle_direction': candle_direction,
            'conflicting_signals': conflicts,
            'all_aligned': len(set(valid_dirs)) <= 1 and len(valid_dirs) > 0,
            'confidence': int(agreement),
        }
    
    def _ema_direction(self, df, m5: Dict[str, Any] = None) -> str:
        try:
            close = df['close'].iloc[-1]
            # Use pre-computed values from payload (SSOT)
            if not m5 or 'ema20' not in m5 or 'ema50' not in m5:
                raise ValueError("FAIL-FAST: Missing ema20/ema50 in payload for conflict_analyzer")
            ema20 = m5['ema20']
            ema50 = m5['ema50']
            if close > ema20 > ema50:
                return 'UP'
            elif close < ema20 < ema50:
                return 'DOWN'
            return 'NONE'
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _momentum_direction(self, df) -> str:
        try:
            closes = df['close']
            roc = (closes.iloc[-1] - closes.iloc[-14]) / closes.iloc[-14] * 100
            if roc > 0.3:
                return 'UP'
            elif roc < -0.3:
                return 'DOWN'
            return 'NONE'
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _candle_direction(self, df) -> str:
        try:
            recent = df.tail(10)
            bullish = (recent['close'] > recent['open']).sum()
            bearish = (recent['close'] < recent['open']).sum()
            if bullish > bearish * 1.5:
                return 'UP'
            elif bearish > bullish * 1.5:
                return 'DOWN'
            return 'NONE'
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error: {e}")
            raise
    
    def _count_conflicts(self, directions: List[str]) -> int:
        """Count pairs that conflict"""
        conflicts = 0
        for i in range(len(directions)):
            for j in range(i + 1, len(directions)):
                if directions[i] != directions[j]:
                    conflicts += 1
        return conflicts
    
    def _calculate_conflict_score(self, directions: List[str]) -> int:
        """Score 0-100 for conflict level"""
        if len(directions) < 2:
            return 0
        
        up = directions.count('UP')
        down = directions.count('DOWN')
        
        # Perfect agreement = 0 conflict
        if up == 0 or down == 0:
            return 0
        
        # Max conflict when evenly split
        total = up + down
        minority = min(up, down)
        conflict = (minority / total) * 100 * 2
        
        return int(min(100, conflict))
    
