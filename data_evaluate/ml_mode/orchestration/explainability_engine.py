"""
TIER 8 - EXPLAINABILITY ENGINE


Generates human-readable explanations of WHY a signal/decision was made.
Critical for trust and debugging.
"""

from typing import Dict, Any, List
from data_evaluate.orchestration.base_engine import BaseEngine


class ExplainabilityEngine(BaseEngine):
    """Tier 8: Explainability Engine - reads MarketContext"""
    
    ENGINE_NAME = "explainability_engine"
    ENGINE_VERSION = "1.0.0"
    TIER = 8
    
    def analyze(self, context=None, **kwargs) -> Dict[str, Any]:
        """Generate explanation of the analysis"""
        try:
            ctx = context or kwargs['context']
            if ctx is None:
                raise ValueError("FAIL-FAST: Neutral state removed")
            
            supporting = self._gather_supporting_factors(ctx)
            opposing = self._gather_opposing_factors(ctx)
            key_drivers = self._identify_key_drivers(ctx)
            summary = self._compose_summary(ctx, supporting, opposing)
            
            return {
                'summary': summary,
                'supporting_factors': supporting,
                'opposing_factors': opposing,
                'key_drivers': key_drivers,
                'factor_balance': len(supporting) - len(opposing),
                'explanation_available': True,
                'confidence': 100,
            }
        except Exception as e:
            raise
    
    def _gather_supporting_factors(self, ctx) -> List[str]:
        """Factors supporting a trade"""
        factors = []
        
        trend_dir = ctx.trend['direction']
        if trend_dir != 'NONE':
            conf = ctx.trend['confidence']
            factors.append(f"Trend is {trend_dir} (confidence {conf})")
        
        mtf_align = ctx.mtf['alignment_score']
        if mtf_align >= 70:
            factors.append(f"Strong MTF alignment ({mtf_align})")
        
        clarity = ctx.synthesized_context['market_clarity']
        if clarity >= 65:
            factors.append(f"Clear market picture ({clarity})")
        
        edge = ctx.move_probability['edge']
        if edge >= 10:
            factors.append(f"Statistical edge present ({edge})")
        
        efficiency = ctx.efficiency['overall_efficiency']
        if efficiency >= 65:
            factors.append(f"Efficient price movement ({efficiency})")
        
        quality = ctx.signal_quality['quality_score']
        if quality >= 70:
            grade = ctx.signal_quality['grade']
            factors.append(f"Good signal quality (grade {grade})")
        
        confirmation = ctx.signal_quality['confirmation_score']
        if confirmation >= 70:
            factors.append(f"Multiple engines confirm direction ({confirmation:.0f})")
        
        return factors
    
    def _gather_opposing_factors(self, ctx) -> List[str]:
        """Factors against a trade"""
        factors = []
        
        if ctx.traps['trap_detected']:
            trap_type = ctx.traps['trap_type']
            factors.append(f"Trap detected ({trap_type})")
        
        noise = ctx.noise['noise_level']
        if noise > 60:
            factors.append(f"High market noise ({noise})")
        
        conflict = ctx.conflict['conflict_score']
        if conflict > 50:
            factors.append(f"Conflicting signals ({conflict})")
        
        if ctx.transition['in_transition']:
            t_type = ctx.transition['transition_type']
            factors.append(f"Market in transition ({t_type})")
        
        exhaustion = ctx.strength['exhaustion_risk']
        if exhaustion > 65:
            factors.append(f"Momentum exhaustion risk ({exhaustion})")
        
        if ctx.mtf['htf_ltf_conflict']:
            factors.append("Higher/Lower timeframe conflict")
        
        if ctx.trend['type'] == 'CHOPPY':
            factors.append("Choppy market - no clear direction")
        
        return factors
    
    def _identify_key_drivers(self, ctx) -> List[str]:
        """Top 3 most influential factors"""
        drivers = []
        
        # The dominant factor is usually the synthesized read
        market_read = ctx.synthesized_context['market_read']
        if market_read:
            drivers.append(market_read)
        
        # Probability direction
        prob_dir = ctx.move_probability['direction']
        up_prob = ctx.move_probability['up_probability']
        if prob_dir != 'NEUTRAL':
            drivers.append(f"Probability favors {prob_dir} ({up_prob}% up)")
        
        # Confidence tier
        conf_tier = ctx.confidence_framework['confidence_tier']
        final_conf = ctx.confidence_framework['final_confidence']
        drivers.append(f"Confidence: {conf_tier} ({final_conf})")
        
        return drivers[:3]
    
    def _compose_summary(self, ctx, supporting, opposing) -> str:
        """One-paragraph plain summary"""
        if isinstance(ctx.market_state, dict):
            state = ctx.market_state['state']
        else:
            state = str(ctx.market_state) if ctx.market_state else 'UNKNOWN'
        direction = ctx.move_probability['direction']
        confidence = ctx.confidence_framework['final_confidence']
        
        sup_count = len(supporting)
        opp_count = len(opposing)
        
        verdict = "favorable" if sup_count > opp_count else (
                  "unfavorable" if opp_count > sup_count else "mixed")
        
        return (
            f"Market is {state} with {direction} bias. "
            f"Final confidence {confidence}. "
            f"{sup_count} supporting vs {opp_count} opposing factors - "
            f"conditions are {verdict}."
        )
    
