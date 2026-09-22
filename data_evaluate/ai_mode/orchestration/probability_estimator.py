"""
TIER 6 - PROBABILITY ESTIMATOR


Estimates probability of price moving UP vs DOWN in the next period.
Combines all evidence into a calibrated probability.

For binary options: this is the core "will it go up or down" estimate.
"""

from typing import Dict, Any
from data_evaluate.orchestration.base_engine import BaseEngine


class ProbabilityEstimator(BaseEngine):
    """Tier 6: Move Probability Estimator - reads MarketContext"""
    
    ENGINE_NAME = "probability_estimator"
    ENGINE_VERSION = "1.0.0"
    TIER = 6
    
    def analyze(self, context=None, **kwargs) -> Dict[str, Any]:
        """Estimate UP/DOWN probability from full context"""
        try:
            ctx = context or kwargs['context']
            if ctx is None:
                raise ValueError("FAIL-FAST: Neutral state removed")
            
            # Collect probabilistic evidence
            up_prob = self._estimate_up_probability(ctx)
            down_prob = 100 - up_prob
            
            # Confidence in the estimate
            estimate_confidence = self._estimate_confidence(ctx, up_prob)
            
            # Expected move magnitude
            expected_magnitude = self._expected_magnitude(ctx)
            
            # Direction
            if up_prob >= 58:
                direction = 'UP'
            elif up_prob <= 42:
                direction = 'DOWN'
            else:
                direction = 'NEUTRAL'
            
            # Edge: how far from 50/50
            edge = abs(up_prob - 50)
            
            return {
                'up_probability': up_prob,
                'down_probability': down_prob,
                'direction': direction,
                'edge': int(edge),
                'estimate_confidence': estimate_confidence,
                'expected_magnitude': expected_magnitude,
                'has_edge': edge >= 8,
                'confidence': estimate_confidence,
            }
        except Exception as e:
            raise
    
    def _estimate_up_probability(self, ctx) -> int:
        """Estimate probability of UP move (0-100) using normalized weights"""
        weights = {
            'trend': 1.2,
            'mtf': 1.0,
            'continuation': 0.8,
            'pressure': 0.8,
            'divergence': 0.6,
            'pattern': 0.5,
            'strength': 0.4
        }
        
        total_weight = sum(weights.values())
        scores = []
        
        # Trend
        trend_dir = ctx.trend['direction']
        trend_conf = ctx.trend['confidence'] / 100.0
        if trend_dir == 'UP': scores.append(1.0 * trend_conf * weights['trend'])
        elif trend_dir == 'DOWN': scores.append(-1.0 * trend_conf * weights['trend'])
        else: scores.append(0)
        
        # MTF
        mtf_dir = ctx.mtf['dominant_direction']
        mtf_align = ctx.mtf['alignment_score'] / 100.0
        if mtf_dir == 'UP': scores.append(1.0 * mtf_align * weights['mtf'])
        elif mtf_dir == 'DOWN': scores.append(-1.0 * mtf_align * weights['mtf'])
        else: scores.append(0)
        
        # Continuation
        cont_prob = (ctx.continuation['continuation_probability'] - 50) / 50.0
        cont_bias = ctx.continuation['bias']
        if cont_bias == 'CONTINUATION' and trend_dir == 'UP': scores.append(cont_prob * weights['continuation'])
        elif cont_bias == 'CONTINUATION' and trend_dir == 'DOWN': scores.append(-cont_prob * weights['continuation'])
        else: scores.append(0)
        
        # Market pressure
        buy_pressure = (ctx.orderflow['buy_pressure'] - 50) / 50.0
        scores.append(buy_pressure * weights['pressure'])
        
        # Divergence
        if ctx.divergence['divergence_detected']:
            div_type = ctx.divergence['divergence_type']
            div_strength = ctx.divergence['divergence_strength'] / 100.0
            if div_type == 'BULLISH': scores.append(1.0 * div_strength * weights['divergence'])
            elif div_type == 'BEARISH': scores.append(-1.0 * div_strength * weights['divergence'])
            else: scores.append(0)
        else:
            scores.append(0)
            
        # Candle pattern
        pattern_bias = ctx.candle_patterns['bias']
        pattern_strength = ctx.candle_patterns['pattern_strength'] / 100.0
        if pattern_bias == 'BULLISH': scores.append(1.0 * pattern_strength * weights['pattern'])
        elif pattern_bias == 'BEARISH': scores.append(-1.0 * pattern_strength * weights['pattern'])
        else: scores.append(0)
        
        # Strength
        rsi = ctx.strength['rsi']
        rsi_normalized = (rsi - 50) / 50.0
        scores.append(rsi_normalized * weights['strength'])
        
        # Calculate final probability
        weighted_sum = sum(scores)
        normalized_score = weighted_sum / total_weight  # Range roughly -1 to 1
        
        # Map from [-1, 1] to [0, 100]
        prob = 50 + (normalized_score * 50)
        
        return int(min(95, max(5, prob)))
    
    def _estimate_confidence(self, ctx, up_prob) -> int:
        """Confidence in the probability estimate using normalized weighting"""
        edge = abs(up_prob - 50)
        edge_score = min(20, edge) / 20.0
        
        conflict = ctx.conflict['conflict_score'] / 100.0
        noise = ctx.noise['noise_level'] / 100.0
        clarity = ctx.synthesized_context['market_clarity'] / 100.0
        
        weights = {
            'edge': 1.0,
            'conflict': 0.8,
            'noise': 0.6,
            'clarity': 0.8
        }
        total_weight = sum(weights.values())
        
        score = (edge_score * weights['edge'] + 
                (1.0 - conflict) * weights['conflict'] + 
                (1.0 - noise) * weights['noise'] + 
                clarity * weights['clarity'])
                
        final_conf = (score / total_weight) * 100
        return int(min(100, max(0, final_conf)))
    
    def _expected_magnitude(self, ctx) -> str:
        """Expected size of the move"""
        regime = ctx.volatility['regime']
        expansion = ctx.volatility['expansion_probability']
        
        if regime == 'EXTREME' or expansion > 70:
            return 'LARGE'
        elif regime == 'HIGH' or expansion > 55:
            return 'MEDIUM'
        elif regime == 'LOW':
            return 'SMALL'
        return 'MEDIUM'
    
