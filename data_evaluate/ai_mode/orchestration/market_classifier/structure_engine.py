"""
TIER 1 - STRUCTURE ENGINE


Detects support/resistance levels, BOS (Break of Structure), and key zones.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple

from data_evaluate.orchestration.base_engine import BaseEngine


class StructureEngine(BaseEngine):
    """Tier 1: Structure Engine"""
    
    ENGINE_NAME = "structure_engine"
    ENGINE_VERSION = "1.0.0"
    TIER = 1
    MIN_CANDLES = 100
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, payload: Dict[str, Any], candles_dict: Dict[str, pd.DataFrame] = None, **kwargs) -> Dict[str, Any]:
        m5 = payload['m5']
        pa = payload['price_action']
        if not m5:
            raise ValueError("FAIL-FAST: Neutral state removed")
        if not candles_dict:
            raise ValueError("FAIL-FAST: Missing candles_dict for structure analysis")
        if 'M5' not in candles_dict or candles_dict['M5'] is None or candles_dict['M5'].empty:
            raise ValueError("FAIL-FAST: Invalid M5 data in candles_dict")
        if len(candles_dict['M5']) < 50:
            raise ValueError("FAIL-FAST: Insufficient M5 candles (minimum 50 required)")
            
        # Validate required indicator fields
        required_fields = ['support', 'resistance', 's1', 'r1', 'pivot', 'box_duration', 'box_tightness']
        for field in required_fields:
            if field not in m5 or m5[field] is None:
                raise ValueError(f"FAIL-FAST: Missing required field in m5: {field}")
                
        # Validate payload structure
        if 'price_action' not in payload:
            raise ValueError("FAIL-FAST: Missing price_action in payload")
            
        # Validate price_action structure
        if not isinstance(payload['price_action'], dict):
            raise ValueError("FAIL-FAST: price_action must be a dictionary")
            
        pa_required_fields = ['sr_interaction', 'move_quality']
        for field in pa_required_fields:
            if field not in payload['price_action'] or payload['price_action'][field] is None:
                raise ValueError(f"FAIL-FAST: Missing required field in price_action: {field}")
            
        support = m5['support']
        resistance = m5['resistance']
        s1 = m5['s1']
        r1 = m5['r1']
        
        support_levels = [s for s in sorted([support, s1]) if s > 0][:3]
        resistance_levels = [r for r in sorted([resistance, r1]) if r > 0][:3]
        
        sr_interaction = pa['sr_interaction']
        move_quality = pa['move_quality']
        
        struct_type = self._determine_structure_type(sr_interaction, move_quality)
        bos_detected, bos_type = self._detect_bos(sr_interaction)
        key_zones = self._find_key_zones(support_levels, resistance_levels, m5['pivot'])
        proximity = self._check_proximity(sr_interaction)
        struct_score = self._score_structure(support_levels, resistance_levels)
        
        box_duration = m5['box_duration']
        box_tightness = m5['box_tightness']
        
        return {
            'support_levels': support_levels,
            'resistance_levels': resistance_levels,
            'structure_type': struct_type,
            'structure_score': struct_score,
            'bos_detected': bool(bos_detected),
            'bos_type': bos_type,
            'key_zones': key_zones,
            'zone_proximity': proximity,
            'breakout_probability': 60 if bos_detected else 30,
            'reversal_probability': 40 if bos_detected else 50,
            'confidence': min(85, struct_score + 10),
            
            # Enhancement 1: Box Duration Tracker metrics
            'box_duration': box_duration,
            'box_tightness': box_tightness,
        }
    
    def _determine_structure_type(self, sr_interaction: str, move_quality: str) -> str:
        if sr_interaction.startswith('BREAKING'):
            return 'BREAKOUT'
        elif move_quality == 'CLEAN_TRENDING':
            return 'TRENDING'
        return 'RANGING'
    
    def _detect_bos(self, sr_interaction: str) -> Tuple[bool, str]:
        if sr_interaction == 'BREAKING_BELOW_SUPPORT':
            return True, 'BEARISH'
        elif sr_interaction == 'BREAKING_ABOVE_RESISTANCE':
            return True, 'BULLISH'
        return False, 'NONE'
    
    def _find_key_zones(self, supports, resistances, pivot) -> Dict[str, float]:
        try:
            return {
                'strong_support': float(supports[0]) if supports else 0.0,
                'strong_resistance': float(resistances[0]) if resistances else 0.0,
                'middle': float(pivot),
            }
        except Exception as e:
            raise
    
    def _check_proximity(self, sr_interaction: str) -> str:
        if sr_interaction in ['NEAR_SUPPORT', 'NEAR_RESISTANCE']:
            return 'NEAR'
        elif sr_interaction in ['BREAKING_ABOVE_RESISTANCE', 'BREAKING_BELOW_SUPPORT']:
            return 'AT_LEVEL'
        elif sr_interaction == 'MIDDLE':
            return 'FAR'
        return 'FAR'
    
    def _score_structure(self, supports, resistances) -> int:
        score = 50
        if len(supports) > 1: score += 15
        if len(resistances) > 1: score += 15
        if len(supports) > 0 and len(resistances) > 0: score += 10
        return min(100, score)
    
