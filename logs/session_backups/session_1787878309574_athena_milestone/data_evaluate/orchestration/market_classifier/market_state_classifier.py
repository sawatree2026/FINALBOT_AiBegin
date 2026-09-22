import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from collections import deque
import traceback
import logging

from data_evaluate.orchestration.base_engine import BaseEngine
from data_evaluate.exceptions import InvalidInputError, ComputationError


class MarketStateClassifier(BaseEngine):
    """
    Tier 2: Market State Classifier - Optimized for 5-minute Binary Options
    
    Key optimizations for 5-min trading:
    - Reduced indicator periods for faster response (ADX 10, RSI 7)
    - Adaptive thresholds based on recent volatility
    - Momentum divergence detection for early reversals
    - Volume-confirmed breakouts
    - State transition smoothing to reduce false flips
    - Dynamic noise filtering with weighted efficiency
    
    Market States (10 types):
    - TRENDING_STRONG      : Clear directional move with strong momentum
    - TRENDING_WEAK        : Directional bias but low conviction
    - SIDEWAY_RANGE        : Price oscillating between clear levels
    - BREAKOUT_EMERGING    : Volatility expansion after compression
    - REVERSAL_FORMING     : Potential trend change, early signals
    - ACCUMULATION         : Smart money buying, lower wicks / volume pattern
    - DISTRIBUTION         : Smart money selling, upper wicks / volume pattern
    - CHOPPY_UNCERTAIN     : Chaotic movement, high noise, avoid trading
    - LIQUIDITY_VOID       : Extreme low volume / dead market
    - UNCLEAR              : Insufficient signals or mixed indicators
    
    Each classification includes confidence score (0-100), quality score (0-100),
    tradeability flag, stability score (0-100), and descriptive text.
    """
    
    ENGINE_NAME = "market_state_classifier"
    ENGINE_VERSION = "5.0.0"  # Optimized for 5-min BO
    TIER = 2
    MIN_CANDLES = 50  # Reduced from 100 for 5-min responsiveness
    
    # State list for validation
    VALID_STATES = [
        'TRENDING_STRONG', 'TRENDING_WEAK', 'SIDEWAY_RANGE',
        'BREAKOUT_EMERGING', 'REVERSAL_FORMING', 'ACCUMULATION',
        'DISTRIBUTION', 'CHOPPY_UNCERTAIN', 'LIQUIDITY_VOID', 'UNCLEAR'
    ]
    
    # State transition smoothing - prevent rapid flipping
    _state_history: deque
    _max_history = 5
    
    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self._state_history = deque(maxlen=self._max_history)
    
    def _analyze(self, payload: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Analyze market state based on SSOT payload and precomputed Tier 1 data.
        
        Args:
            payload: SSOT dictionary containing 'm5', 'price_action', 'ohlcv'
            **kwargs:
                - trend_data
                - strength_data
                - volatility_data
                - structure_data
                - mtf_data
                - symbol
        """
        if not isinstance(payload, dict):
            raise InvalidInputError(f"[{self.ENGINE_NAME}] payload must be a dictionary")
        if 'm5' not in payload:
            raise InvalidInputError(f"[{self.ENGINE_NAME}] 'm5' missing from payload")
        if 'price_action' not in payload:
            raise InvalidInputError(f"[{self.ENGINE_NAME}] 'price_action' missing from payload")
        if 'ohlcv' not in payload:
            raise InvalidInputError(f"[{self.ENGINE_NAME}] 'ohlcv' missing from payload")

        required_kwargs = ['trend_data', 'strength_data', 'volatility_data', 'structure_data', 'mtf_data', 'symbol', 'candles_dict']

        for req in required_kwargs:
            if req not in kwargs:
                raise InvalidInputError(f"[{self.ENGINE_NAME}] Missing required kwarg: {req}")
            if kwargs[req] is None:
                raise InvalidInputError(f"[{self.ENGINE_NAME}] Required kwarg {req} cannot be None")

        trend_data = kwargs['trend_data']
        strength_data = kwargs['strength_data']
        volatility_data = kwargs['volatility_data']
        structure_data = kwargs['structure_data']
        mtf_data = kwargs['mtf_data']
        symbol = kwargs['symbol']
        candles_dict = kwargs['candles_dict']
        
        is_otc = (symbol.upper().endswith('_OTC') or symbol.upper().endswith('-OTC')) if isinstance(symbol, str) else False
        
        metrics = self._compute_metrics(payload, trend_data, strength_data,
                                        volatility_data, structure_data, mtf_data,
                                        candles_dict, is_otc=is_otc)
        
        state, confidence = self._classify_state(metrics, is_otc=is_otc)
        state = self._smooth_state(state, confidence)
        
        quality_score = self._calculate_quality_score(state, metrics)
        tradeable = self._is_tradeable(state, quality_score, metrics)
        stability = self._compute_stability(metrics)
        description = self._describe_state(state, metrics)
        # Determine Risk Level
        risk_level = 'HIGH' if metrics['noise_level'] > 0.5 or metrics['volatility_regime'] == 'EXTREME' else ('LOW' if metrics['noise_level'] < 0.25 and metrics['volatility_regime'] == 'NORMAL' else 'MEDIUM')
        
        # Action and Expiry
        action = 'รอการวิเคราะห์จาก AI'
        expiry = 5
        
        return {
            'state': state,
            'confidence': int(confidence),
            'quality_score': int(quality_score),
            'tradeable': tradeable,
            'stability': int(stability),
            'description': description,
            'breakout_prob': metrics.get('breakout_prob', 0),
            'reversal_prob': metrics.get('reversal_prob', 0),
            'risk_level': risk_level,
            'suggested_action': action,
            'suggested_expiry': expiry,
            'metrics': metrics
        }

    
    def _compute_metrics(self, payload: Dict[str, Any],
                        trend_data: Dict, strength_data: Dict,
                        volatility_data: Dict, structure_data: Dict,
                        mtf_data: Dict, candles_dict: Dict, is_otc: bool = False) -> Dict[str, Any]:
        
        m5 = payload['m5']
        pa = payload['price_action']
        meta = payload['ohlcv']
        
        close = m5['close']
        
        # Engine Data
        trend_direction = trend_data['direction']
        trend_strength = trend_data['strength']
        trend_slope = trend_data['slope']
        trend_type = trend_data['type']
        
        adx = strength_data['adx']
        rsi = strength_data['rsi']
        momentum_level = strength_data['momentum_level']
        strength_score = strength_data['strength_score']
        
        atr_percentile = volatility_data['atr_percentile']
        bbw = volatility_data['bbw']
        volatility_regime = volatility_data['regime']
        volatility_score = volatility_data['volatility_score']
        
        structure_type = structure_data['structure_type']
        bos_detected = structure_data['bos_detected']
        breakout_prob = structure_data['breakout_probability']
        reversal_prob = structure_data['reversal_probability']
        
        alignment_score = mtf_data['alignment_score']
        htf_direction = mtf_data['htf_direction']
        
        # Payload Data
        volume_ratio = 1.0 if is_otc else m5['volume_ratio']
        volume_surge = volume_ratio > 1.5
        
        # Noise level from move_quality
        move_quality = pa['move_quality']
        noise_level = 0.2 if move_quality == 'CLEAN_TRENDING' else 0.8 if move_quality == 'NOISY' else 0.5
        
        rsi_extreme_bull = rsi > 75
        rsi_extreme_bear = rsi < 25
        
        price_above_ma20 = close > m5['ema20']
        price_above_ma50 = close > m5['ema50']
        
        wick_dominance = pa['wick_dominance']
        wick_lower_ratio = 0.6 if wick_dominance == 'HIGH_LOWER_WICK' else 0.3
        wick_upper_ratio = 0.6 if wick_dominance == 'HIGH_UPPER_WICK' else 0.3
        
        compression_detected = bbw < 0.05 or m5['box_tightness'] < 1.0
        
        sr_interaction = pa['sr_interaction']
        divergence_detected = False
        if rsi < 35 and sr_interaction == 'NEAR_SUPPORT':
            divergence_detected = True
        elif rsi > 65 and sr_interaction == 'NEAR_RESISTANCE':
            divergence_detected = True
            
        adaptive_adx_threshold = 18 if atr_percentile < 60 else 28 if atr_percentile > 140 else 22

        # Regime Quality Metrics from df_m5
        df_m5 = candles_dict.get('M5')
        if df_m5 is not None and not df_m5.empty:
            consistency = self._calculate_consistency(df_m5)
            cleanliness = self._calculate_cleanliness(df_m5)
            directionality = self._calculate_directionality(df_m5)
            regime_quality = int((consistency + cleanliness + directionality) / 3)
        else:
            consistency = cleanliness = directionality = regime_quality = 50
        
        return {
            'trend_direction': trend_direction,
            'trend_strength': trend_strength,
            'trend_slope': trend_slope,
            'trend_type': trend_type,
            'adx': adx,
            'rsi': rsi,
            'momentum_level': momentum_level,
            'strength_score': strength_score,
            'atr_percentile': atr_percentile,
            'bbw': bbw,
            'volatility_regime': volatility_regime,
            'volatility_score': volatility_score,
            'structure_type': structure_type,
            'bos_detected': bos_detected,
            'breakout_prob': breakout_prob,
            'reversal_prob': reversal_prob,
            'alignment_score': alignment_score,
            'htf_direction': htf_direction,
            'volume_ratio': volume_ratio,
            'noise_level': noise_level,
            'rsi_extreme_bull': rsi_extreme_bull,
            'rsi_extreme_bear': rsi_extreme_bear,
            'price_above_ma20': price_above_ma20,
            'price_above_ma50': price_above_ma50,
            'wick_lower_ratio': wick_lower_ratio,
            'wick_upper_ratio': wick_upper_ratio,
            'compression_detected': compression_detected,
            'divergence_detected': divergence_detected,
            'volume_surge': volume_surge,
            'adaptive_adx_threshold': adaptive_adx_threshold,
            'consistency_score': consistency,
            'cleanliness_score': cleanliness,
            'directionality_score': directionality,
            'regime_quality_score': regime_quality,
            'is_otc': is_otc
        }
    
    def _classify_state(self, m: Dict[str, Any], is_otc: bool = False) -> tuple:
        """
        Determine market state using a weighted scoring system.
        Returns (state, confidence) where confidence is 0-100 integer.
        
        For OTC pairs (is_otc=True), LIQUIDITY_VOID score is forced to 0
        because volume data is not reliable in OTC markets.
        """
        # Compute raw scores for all states
        raw_scores = self._compute_raw_scores(m)
        
        # Apply global modifiers (boosts/penalties)
        adjusted_scores = self._apply_global_modifiers(raw_scores, m, is_otc)
        
        # For OTC, explicitly zero out LIQUIDITY_VOID
        if is_otc:
            adjusted_scores['LIQUIDITY_VOID'] = 0
        
        # Select best state
        best_state = max(adjusted_scores, key=adjusted_scores.get)
        best_score = adjusted_scores[best_state]
        
        # Calculate confidence based on score margin over second best
        sorted_scores = sorted(adjusted_scores.values(), reverse=True)
        if len(sorted_scores) >= 2 and sorted_scores[0] > 0:
            margin = sorted_scores[0] - sorted_scores[1]
            # Confidence: base 50% + margin contribution, capped at 100
            confidence = min(100, int(50 + (margin / 100) * 50))
        else:
            confidence = 50
        
        # Prevent rapid switching: if best_state is LIQUIDITY_VOID but previous wasn't,
        # require a significant margin (>=15 points) to switch
        if best_state == 'LIQUIDITY_VOID' and self._state_history:
            prev_state, _ = self._state_history[-1]
            if prev_state != 'LIQUIDITY_VOID' and len(sorted_scores) >= 2:
                if margin < 15:
                    # Fall back to second best (unless it's also LIQUIDITY_VOID)
                    second_best = sorted(adjusted_scores.items(), key=lambda x: x[1], reverse=True)[1][0]
                    if second_best != 'LIQUIDITY_VOID':
                        best_state = second_best
                        best_score = adjusted_scores[best_state]
                        confidence = min(100, int(50 + ((best_score - sorted_scores[1]) / 100) * 50))
        
        return best_state, max(0, min(100, confidence))
    
    def _compute_raw_scores(self, m: Dict[str, Any]) -> Dict[str, float]:
        """Compute raw score for each state based on the weighted scoring system."""
        scores = {}
        
        # Extract metrics
        adx = m['adx']
        trend_strength = m['trend_strength']
        direction = m['trend_direction']
        atr_percentile = m['atr_percentile']
        bbw = m['bbw']
        volatility_regime = m['volatility_regime']
        structure_type = m['structure_type']
        bos_detected = m['bos_detected']
        breakout_prob = m['breakout_prob']
        reversal_prob = m['reversal_prob']
        volume_ratio = m['volume_ratio']
        is_otc = m['is_otc']
        noise_level = m['noise_level']
        alignment_score = m['alignment_score']
        htf_ltf_conflict = m.get('htf_ltf_conflict', False)
        exhaustion_risk = m.get('exhaustion_risk', 0.0)
        divergence_detected = m['divergence_detected']
        rsi = m['rsi']
        wick_lower_ratio = m['wick_lower_ratio']
        wick_upper_ratio = m['wick_upper_ratio']
        
        # ----- TRENDING_STRONG -----
        score = (adx / 100) * 35
        score += (trend_strength / 100) * 30
        score += (alignment_score / 100) * 20
        score += (1 - noise_level) * 15
        # Boosts
        if direction != 'NONE':
            score += 10
        if structure_type in ['TRENDING', 'BREAKOUT']:
            score += 10
        if bos_detected:
            score += 5
        if alignment_score >= 70:
            score += 10
        # Penalties
        if noise_level > 0.6:
            score -= 20
        if exhaustion_risk > 70:
            score -= 20
        if htf_ltf_conflict:
            score -= 15
        scores['TRENDING_STRONG'] = max(0, score)
        
        # ----- BREAKOUT_EMERGING -----
        score = max(0, (0.06 - bbw) / 0.06) * 30
        score += (100 - atr_percentile) / 100 * 20
        score += (breakout_prob / 100) * 25
        score += (1 if bos_detected else 0) * 15
        # Volume factor
        if not is_otc:
            score += min(1.0, volume_ratio / 1.5) * 10
        else:
            score += 10  # full volume credit for OTC
        # Boosts
        if bbw < 0.04:
            score += 15
        if atr_percentile < 30:
            score += 10
        if not is_otc and volume_ratio > 1.5:
            score += 10
        # Penalties
        if noise_level > 0.5:
            score -= 15
        if htf_ltf_conflict:
            score -= 20
        scores['BREAKOUT_EMERGING'] = max(0, score)
        
        # ----- SIDEWAY_RANGE -----
        score = (100 - adx) / 100 * 35
        score += (1 if structure_type == 'RANGING' else 0) * 25
        score += (1 - noise_level) * 20
        score += (1 if volatility_regime in ['LOW', 'NORMAL'] else 0) * 20
        # Boosts
        if adx < 18:
            score += 15
        if noise_level < 0.3:
            score += 10
        # Penalties
        if bos_detected:
            score -= 20
        if breakout_prob > 50:
            score -= 15
        scores['SIDEWAY_RANGE'] = max(0, score)
        
        # ----- ACCUMULATION -----
        score = min(1.0, wick_lower_ratio * 2) * 35
        # Volume factor
        if not is_otc:
            score += min(1.0, volume_ratio / 1.2) * 25
        else:
            score += 25
        score += ((100 - trend_strength) / 100) * 20
        score += (1 if structure_type in ['RANGING', 'CORRECTIVE'] else 0) * 20
        # Boosts
        if not is_otc and volume_ratio > 1.2:
            score += 15
        if wick_lower_ratio > 0.5:
            score += 10
        # Penalties
        if bos_detected:
            score -= 15
        if divergence_detected:
            score -= 10
        scores['ACCUMULATION'] = max(0, score)
        
        # ----- DISTRIBUTION -----
        score = min(1.0, wick_upper_ratio * 2) * 35
        if not is_otc:
            score += min(1.0, volume_ratio / 1.2) * 25
        else:
            score += 25
        score += ((100 - trend_strength) / 100) * 20
        score += (1 if structure_type in ['RANGING', 'CORRECTIVE'] else 0) * 20
        # Boosts
        if not is_otc and volume_ratio > 1.2:
            score += 15
        if wick_upper_ratio > 0.5:
            score += 10
        # Penalties
        if bos_detected:
            score -= 15
        if divergence_detected:
            score -= 10
        scores['DISTRIBUTION'] = max(0, score)
        
        # ----- TRENDING_WEAK -----
        score = (adx / 100) * 30
        score += (trend_strength / 100) * 25
        score += (1 - noise_level) * 25
        score += (alignment_score / 100) * 20
        # Boosts
        if direction != 'NONE':
            score += 10
        if structure_type in ['TRENDING', 'CORRECTIVE']:
            score += 5
        # Penalties
        if exhaustion_risk > 70:
            score -= 25
        if htf_ltf_conflict:
            score -= 10
        if noise_level > 0.5:
            score -= 15
        scores['TRENDING_WEAK'] = max(0, score)
        
        # ----- REVERSAL_FORMING -----
        score = (reversal_prob / 100) * 35
        score += (100 - adx) / 100 * 25
        score += (1 if divergence_detected else 0) * 20
        score += (1 - noise_level) * 20
        # Boosts
        if rsi < 30 or rsi > 70:
            score += 15
        if structure_type == 'CORRECTIVE':
            score += 10
        # Penalties
        if noise_level > 0.5:
            score -= 15
        if htf_ltf_conflict:
            score -= 10
        scores['REVERSAL_FORMING'] = max(0, score)
        
        # ----- CHOPPY_UNCERTAIN -----
        score = noise_level * 100 * 0.6
        score += (100 - adx) / 100 * 20
        score += (1 if structure_type == 'CHOPPY' else 0) * 20
        # Penalties (lower score for choppy)
        if trend_strength > 40:
            score -= 20
        if alignment_score > 50:
            score -= 15
        scores['CHOPPY_UNCERTAIN'] = max(0, score)
        
        # ----- LIQUIDITY_VOID -----
        # Use inverse of volume and ADX as indicators of void
        if not is_otc:
            score = (1 - min(1.0, volume_ratio / 0.5)) * 50
            score += (1 - min(1.0, adx / 20)) * 50
        else:
            score = 0  # will be zeroed in _classify_state
        scores['LIQUIDITY_VOID'] = max(0, score)
        
        # ----- UNCLEAR -----
        # Default moderate score when nothing else fits
        score = 25
        # Increase if most scores are low
        other_scores = [scores[k] for k in scores if k != 'UNCLEAR']
        if all(s < 30 for s in other_scores):
            score = 50
        if htf_ltf_conflict or noise_level > 0.6:
            score += 20
        scores['UNCLEAR'] = max(0, min(100, score))
        
        return scores
    
    def _apply_global_modifiers(self, scores: Dict[str, float], m: Dict[str, Any], is_otc: bool) -> Dict[str, float]:
        """Apply global boosts and penalties to all state scores."""
        adjusted = dict(scores)
        
        noise_level = m.get('noise_level', 0.0)
        htf_ltf_conflict = m.get('htf_ltf_conflict', False)
        exhaustion_risk = m.get('exhaustion_risk', 0.0)
        volatility_regime = m['volatility_regime']
        volume_ratio = m['volume_ratio']
        is_otc = m['is_otc']
        
        # Global modifiers
        modifiers = []
        
        # Low noise boost
        if noise_level < 0.25:
            modifiers.append(('TRENDING_STRONG', 10))
            modifiers.append(('SIDEWAY_RANGE', 10))
        
        # Volume surge boost
        if not is_otc and volume_ratio > 1.5:
            modifiers.append(('BREAKOUT_EMERGING', 15))
            modifiers.append(('ACCUMULATION', 15))
            modifiers.append(('DISTRIBUTION', 15))
        
        # HTF-LTF conflict penalty
        if htf_ltf_conflict:
            for state in adjusted:
                if state != 'UNCLEAR':
                    adjusted[state] -= 15
        
        # High noise penalty
        if noise_level > 0.6:
            adjusted['TRENDING_STRONG'] -= 20
            adjusted['BREAKOUT_EMERGING'] -= 20
        
        # Exhaustion penalty
        if exhaustion_risk > 70:
            adjusted['TRENDING_STRONG'] -= 25
            adjusted['TRENDING_WEAK'] -= 25
        
        # Extreme volatility penalty
        if volatility_regime == 'EXTREME':
            for state in adjusted:
                if state != 'UNCLEAR':
                    adjusted[state] -= 20
        
        # Apply modifiers
        for state, boost in modifiers:
            if state in adjusted:
                adjusted[state] += boost
        
        # Clamp to 0-100
        for state in adjusted:
            adjusted[state] = max(0, min(100, adjusted[state]))
        
        return adjusted
    
    def _smooth_state(self, state: str, confidence: int) -> str:
        """
        Apply state transition smoothing to prevent rapid flipping.
        Requires at least N consecutive same-state classifications before changing.
        """
        self._state_history.append((state, confidence))
        if len(self._state_history) < self._max_history:
            return state
        
        # Count occurrences of each state in history
        from collections import Counter
        counter = Counter(s for s, _ in self._state_history)
        most_common_state, count = counter.most_common(1)[0]
        
        # If the most common state appears at least 3 times, use it
        if count >= 3:
            return most_common_state
        return state
    
    def _calculate_quality_score(self, state: str, m: Dict[str, Any]) -> float:
        """Calculate quality score (0-100) based on state and metrics."""
        # Base quality by state
        state_quality = {
            'TRENDING_STRONG': 90,
            'BREAKOUT_EMERGING': 85,
            'ACCUMULATION': 80,
            'SIDEWAY_RANGE': 75,
            'TRENDING_WEAK': 65,
            'REVERSAL_FORMING': 60,
            'DISTRIBUTION': 45,
            'CHOPPY_UNCERTAIN': 20,
            'LIQUIDITY_VOID': 10,
            'UNCLEAR': 15
        }
        quality = state_quality[state]
        
        # Adjust based on noise level
        noise_penalty = int(m['noise_level'] * 30)
        quality = max(0, quality - noise_penalty)
        
        # Adjust based on volume
        volume_ratio = m['volume_ratio']
        if volume_ratio < 0.5:
            quality = max(0, quality - 20)
            
        # Incorporate regime quality (weighted 50% base, 50% statistical regime quality)
        regime_quality = m.get('regime_quality_score', 50)
        final_quality = (quality + regime_quality) / 2
        
        return min(100, max(0, final_quality))
    
    def _is_tradeable(self, state: str, quality: float, m: Dict[str, Any]) -> bool:
        """
        Evaluate market tradeability based on basic data completeness.
        Note: The actual decision to trade or not trade is NOT the responsibility of Part 2.
        It is delegated to Part 3 (Trade Execution/Logic). This function only returns True
        if the basic data completeness criteria are met.
        """
        if not isinstance(m, dict) or not m:
            return False
        required_keys = ['trend_direction', 'adx', 'rsi', 'noise_level']
        for k in required_keys:
            if k not in m or m[k] is None:
                return False
        return True
    
    def _compute_stability(self, m: Dict[str, Any]) -> float:
        """Compute market stability score (0-100)."""
        noise = m['noise_level']
        volatility = m['volatility_score'] / 100
        adx = m['adx'] / 50
        
        stability = 100 * (1 - noise) * (1 - volatility * 0.3) * (0.5 + 0.5 * min(1, adx))
        return min(100, max(0, stability))
    
    def _describe_state(self, state: str, m: Dict[str, Any]) -> str:
        """Generate human-readable description of the market state."""
        descriptions = {
            'TRENDING_STRONG': 'Strong directional trend with high momentum. Favorable for trend-following strategies.',
            'TRENDING_WEAK': 'Weak directional bias. Caution advised, consider range-bound strategies.',
            'SIDEWAY_RANGE': 'Price ranging between clear levels. Suitable for mean-reversion strategies.',
            'BREAKOUT_EMERGING': 'Volatility expansion after compression. Potential breakout opportunity.',
            'REVERSAL_FORMING': 'Early signals of potential trend change. Watch for confirmation.',
            'ACCUMULATION': 'Smart money accumulation. Bullish bias, look for breakout.',
            'DISTRIBUTION': 'Smart money distribution. Bearish bias, look for breakdown.',
            'CHOPPY_UNCERTAIN': 'Chaotic price action, high noise. Avoid trading until clarity returns.',
            'LIQUIDITY_VOID': 'Extremely low volume / dead market. No trading opportunity.',
            'UNCLEAR': 'Mixed signals or insufficient data. Exercise caution.'
        }
        base = descriptions[state]
        # Add extra details if helpful
        if state in ['BREAKOUT_EMERGING', 'REVERSAL_FORMING']:
            extra = []
            if m.get('divergence_detected', False):
                extra.append("divergence detected")
            if extra:
                return f"{base} ({', '.join(extra)})"
        return base
        
    def _calculate_consistency(self, df: pd.DataFrame) -> int:
        """How consistent are recent moves?"""
        try:
            returns = df['close'].pct_change().tail(50)
            if returns.std() == 0:
                return 50
            
            # Lower std = more consistent
            std = returns.std()
            mean = abs(returns.mean())
            
            # Sharpe-like metric
            if std > 0:
                ratio = mean / std
                return min(100, int(50 + ratio * 100))
            return 50
        except Exception:
            return 50
            
    def _calculate_cleanliness(self, df: pd.DataFrame) -> int:
        """How clean (vs noisy) is the price action?"""
        try:
            highs = df['high'].tail(30)
            lows = df['low'].tail(30)
            closes = df['close'].tail(30)
            opens = df['open'].tail(30)
            
            # Calculate average wick size relative to body
            wicks = (highs - lows) - abs(closes - opens)
            wick_ratio = wicks.mean() / (highs.mean() - lows.mean() + 0.00001)
            
            # Lower wicks = cleaner
            cleanliness = max(20, min(100, 100 - wick_ratio * 100))
            return int(cleanliness)
        except Exception:
            return 50
            
    def _calculate_directionality(self, df: pd.DataFrame) -> int:
        """How directional are moves?"""
        try:
            closes = df['close'].tail(30)
            total_move = abs(closes.iloc[-1] - closes.iloc[0])
            path_length = closes.diff().abs().sum()
            
            if path_length == 0:
                return 50
            
            efficiency = (total_move / path_length) * 100
            return int(min(100, efficiency))
        except Exception:
            return 50
