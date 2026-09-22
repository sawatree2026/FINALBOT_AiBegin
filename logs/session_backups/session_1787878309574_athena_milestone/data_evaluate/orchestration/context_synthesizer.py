"""
TIER 6 - CONTEXT SYNTHESIZER


Synthesizes all Tier 1-5 outputs into a unified market picture.
This is where the system "understands" the market holistically.

Operates on MarketContext (reads all prior tiers).
"""

from typing import Dict, Any
from data_evaluate.orchestration.base_engine import BaseEngine


class ContextSynthesizer(BaseEngine):
    """Tier 6: Context Synthesizer - reads MarketContext directly"""
    
    ENGINE_NAME = "context_synthesizer"
    ENGINE_VERSION = "1.0.0"
    TIER = 6
    
    def analyze(self, context=None, **kwargs) -> Dict[str, Any]:
        """
        Synthesize. Accepts MarketContext via 'context' kwarg.
        ContextBuilder passes context for Tier 6+ engines.
        """
        try:
            ctx = context or kwargs['context']
            if ctx is None:
                raise ValueError("FAIL-FAST: Neutral state removed")
            
            # Synthesize directional bias
            directional_bias, bias_strength = self._synthesize_direction(ctx)
            
            # Synthesize market clarity
            clarity = self._synthesize_clarity(ctx)
            
            # Synthesize risk picture
            risk_level = self._synthesize_risk(ctx)
            
            # Overall market read
            market_read = self._compose_market_read(
                ctx, directional_bias, clarity, risk_level
            )
            
            # Tradeable assessment
            tradeable = self._is_tradeable(clarity, risk_level, ctx)
            
            return {
                'directional_bias': directional_bias,
                'bias_strength': bias_strength,
                'market_clarity': clarity,
                'risk_level': risk_level,
                'market_read': market_read,
                'tradeable': tradeable,
                'synthesis_quality': self._synthesis_quality(clarity, risk_level),
                'confidence': clarity,
            }
        except Exception as e:
            raise
    
    def _synthesize_direction(self, ctx):
        """Combine all directional signals into one bias"""
        weights = {
            'trend': 3.0,
            'mtf': 3.0,
            'ema': 2.0,
            'pattern': 1.0,
            'pa': 1.0
        }
        total_weight = sum(weights.values())
        
        votes = {'UP': 0.0, 'DOWN': 0.0}
        
        # Trend
        trend_dir = ctx.trend['direction']
        if trend_dir in votes:
            votes[trend_dir] += weights['trend'] * (ctx.trend['confidence'] / 100)
            
        # MTF
        mtf_dir = ctx.mtf['dominant_direction']
        if mtf_dir in votes:
            votes[mtf_dir] += weights['mtf'] * (ctx.mtf['alignment_score'] / 100)
            
        # Conflict analyzer EMA direction
        ema_dir = ctx.conflict['ema_direction']
        if ema_dir in votes:
            votes[ema_dir] += weights['ema']
            
        # Candle patterns bias
        pattern_bias = ctx.candle_patterns['bias']
        if pattern_bias == 'BULLISH':
            votes['UP'] += weights['pattern']
        elif pattern_bias == 'BEARISH':
            votes['DOWN'] += weights['pattern']
            
        # Price action bias
        pa_bias = ctx.price_action.get('directional_bias') or ctx.price_action.get('momentum_bias') or ctx.price_action.get('last_candle_bias') or 'NONE'
        if pa_bias in ('BULLISH', 'UP'):
            votes['UP'] += weights['pa']
        elif pa_bias in ('BEARISH', 'DOWN'):
            votes['DOWN'] += weights['pa']
            
        total_votes = votes['UP'] + votes['DOWN']
        if total_votes == 0:
            return 'NONE', 0
            
        if votes['UP'] > votes['DOWN']:
            direction = 'UP'
            strength = int((votes['UP'] / total_votes) * 100)
        elif votes['DOWN'] > votes['UP']:
            direction = 'DOWN'
            strength = int((votes['DOWN'] / total_votes) * 100)
        else:
            return 'NONE', 50
            
        return direction, strength
    
    def _synthesize_clarity(self, ctx) -> int:
        """How clear is the market picture (0-100)"""
        weights = {
            'conflict': 0.3,
            'noise': 0.3,
            'efficiency': 0.2,
            'mtf_align': 0.1,
            'regime': 0.1
        }
        
        conflict_score = ctx.conflict['conflict_score'] / 100.0
        noise_level = ctx.noise['noise_level'] / 100.0
        efficiency = ctx.efficiency['overall_efficiency'] / 100.0
        mtf_align = ctx.mtf['alignment_score'] / 100.0
        regime_q = ctx.regime_quality['overall_quality'] / 100.0
        
        score = ((1.0 - conflict_score) * weights['conflict'] +
                 (1.0 - noise_level) * weights['noise'] +
                 efficiency * weights['efficiency'] +
                 mtf_align * weights['mtf_align'] +
                 regime_q * weights['regime'])
                 
        total_weight = sum(weights.values())
        clarity = (score / total_weight) * 100
        return int(min(100, max(0, clarity)))
    
    def _synthesize_risk(self, ctx) -> int:
        """Aggregate risk level (0-100, high = risky)"""
        risk = 0
        
        if ctx.traps['trap_detected']:
            risk += 30
        if ctx.transition['in_transition']:
            risk += 20
        
        noise = ctx.noise['noise_level']
        risk += noise * 0.2
        
        exhaustion = ctx.strength['exhaustion_risk']
        risk += exhaustion * 0.15
        
        conflict = ctx.conflict['conflict_score']
        risk += conflict * 0.15
        
        return int(min(100, max(0, risk)))
    
    def _compose_market_read(self, ctx, bias, clarity, risk) -> str:
        """Human-readable market summary"""
        if isinstance(ctx.market_state, dict):
            state = ctx.market_state['state']
        else:
            state = str(ctx.market_state) if ctx.market_state else 'UNKNOWN'
        
        if risk > 65:
            return f"{state} but HIGH RISK - caution advised"
        if clarity < 35:
            return f"{state} - UNCLEAR picture, signals conflicting"
        if clarity > 70 and risk < 35:
            return f"{state} - CLEAR {bias} bias, favorable conditions"
        return f"{state} - {bias} bias, moderate clarity"
    
    def _is_tradeable(self, clarity, risk, ctx) -> bool:
        """
        Evaluate data completeness and quality for trading analysis.
        Does not block trading based on arbitrary risk/clarity thresholds or hardcoded rules.
        Returns True when context and market_state data are complete.
        """
        if ctx is None:
            return False
        if not hasattr(ctx, 'market_state') or ctx.market_state is None:
            return False
        return True
    
    def _synthesis_quality(self, clarity, risk) -> int:
        """Quality of the synthesis 0-100"""
        return int(max(0, min(100, clarity - risk * 0.5)))
    
