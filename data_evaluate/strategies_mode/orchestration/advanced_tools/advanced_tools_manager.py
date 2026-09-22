import logging
import pandas as pd
from typing import Dict, Any

from data_evaluate.strategies_mode.orchestration.advanced_tools.behavior_analyzer import BehaviorAnalyzer
from data_evaluate.strategies_mode.orchestration.advanced_tools.candle_pattern_analyzer import CandlePatternAnalyzer
from data_evaluate.strategies_mode.orchestration.advanced_tools.conflict_analyzer import ConflictAnalyzer
from data_evaluate.strategies_mode.orchestration.advanced_tools.continuation_analyzer import ContinuationAnalyzer
from data_evaluate.strategies_mode.orchestration.advanced_tools.divergence_analyzer import DivergenceAnalyzer
from data_evaluate.strategies_mode.orchestration.advanced_tools.efficiency_analyzer import EfficiencyAnalyzer
from data_evaluate.strategies_mode.orchestration.advanced_tools.persistence_analyzer import PersistenceAnalyzer
from data_evaluate.strategies_mode.orchestration.advanced_tools.price_action_handler import PriceActionHandler
from data_evaluate.strategies_mode.orchestration.advanced_tools.transition_analyzer import TransitionAnalyzer
from data_evaluate.strategies_mode.orchestration.trap_detector import TrapDetector

logger = logging.getLogger("AdvancedToolsManager")

class AdvancedToolsManager:
    def __init__(self):
        self.behavior = BehaviorAnalyzer()
        self.candle_pattern = CandlePatternAnalyzer()
        self.conflict = ConflictAnalyzer()
        self.continuation = ContinuationAnalyzer()
        self.divergence = DivergenceAnalyzer()
        self.efficiency = EfficiencyAnalyzer()
        self.persistence = PersistenceAnalyzer()
        self.transition = TransitionAnalyzer()
        
        # This was previously in indicator_store
        self.price_action = PriceActionHandler()
        self.trap_detector = TrapDetector()

    def analyze_all(self, symbol: str, basic_payload: Dict[str, Any], df_m5: Any) -> Dict[str, Any]:
        """
        Runs all advanced analyzers using the M5 DataFrame and basic payload.
        Returns a dictionary of all advanced metrics.
        """
        results = {}
        
        if not isinstance(df_m5, pd.DataFrame) or df_m5.empty:
            raise ValueError("FAIL-FAST: Cannot compute support/resistance from M5 OHLCV")
        
        # Run specialized analyzers
        candle_data = self.candle_pattern.analyze(df_m5)
        trap_data = self.trap_detector.analyze(df_m5)
        pa_data = self.price_action.analyze(df_m5)
        behavior_data = self.behavior.analyze(df_m5)
        conflict_data = self.conflict.analyze(df_m5, basic_payload=basic_payload)
        continuation_data = self.continuation.analyze(df_m5, basic_payload=basic_payload)
        divergence_data = self.divergence.analyze(df_m5, basic_payload=basic_payload)
        efficiency_data = self.efficiency.analyze(df_m5)
        persistence_data = self.persistence.analyze(df_m5, basic_payload=basic_payload)
        transition_data = self.transition.analyze(df_m5)
        
        # Format Price Action for Group B
        patterns = candle_data['patterns_detected']
        
        # Use simple heuristic for body strength and wick dominance
        body_size = pa_data['recent_body_size']
        wick_ratio = pa_data['wick_to_body_ratio']
        
        # Calculate upper vs lower wick dominance from recent candles
        recent_20 = df_m5.tail(20)
        upper_wicks = (recent_20['high'] - recent_20[['open', 'close']].max(axis=1)).sum()
        lower_wicks = (recent_20[['open', 'close']].min(axis=1) - recent_20['low']).sum()
        
        if wick_ratio > 1.0:
            wick_dominance = 'HIGH_UPPER_WICK' if upper_wicks > lower_wicks else 'HIGH_LOWER_WICK'
        else:
            wick_dominance = 'LOW_WICK'
        
        m5_basic = basic_payload['m5']
        meta_basic = basic_payload['meta']
        close_price = m5_basic['close']
        
        # Support and Resistance from Floor Pivot methodology (UNIFIED with pivot)
        # Using S1 as support and R1 as resistance from Floor Pivot calculation
        # This ensures consistency between pivot, support, and resistance
        floor_support = m5_basic.get('s1')
        floor_resistance = m5_basic.get('r1')

        if not isinstance(floor_support, (int, float)) or pd.isna(floor_support) or floor_support <= 0 or \
           not isinstance(floor_resistance, (int, float)) or pd.isna(floor_resistance) or floor_resistance <= 0:
            raise ValueError("FAIL-FAST: Invalid Floor Pivot support/resistance from indicator_store")

        support = float(floor_support)
        resistance = float(floor_resistance)

        atr = m5_basic['atr14']
        
        # Inject back into a new m5 dict to respect immutability
        # Using Floor Pivot S1/R1 for support/resistance (unified with pivot)
        new_m5 = m5_basic.copy()
        new_m5['support'] = round(support, 6)
        new_m5['resistance'] = round(resistance, 6)
        new_m5['volume_trend'] = pa_data['volume_momentum']
        results['m5'] = new_m5
        
        pivot = m5_basic['pivot']
        rejection_zone = "NONE"
        sr_interaction = "NONE"
        
        if not (close_price and isinstance(close_price, (int, float)) and close_price > 0):
            raise ValueError("close_price is missing or invalid")
        if not (atr and isinstance(atr, (int, float)) and atr > 0):
            raise ValueError("atr is missing or invalid")
            
        threshold = atr * 0.5

        # sr_interaction - FIXED: Move outside rejection_zone block so all 3 values can be set
        # BOS detection: price breaks beyond S/R level (not just testing)
        if resistance and isinstance(resistance, (int, float)) and resistance > 0 and close_price > resistance:
            sr_interaction = "BREAKING_ABOVE_RESISTANCE"
        elif support and isinstance(support, (int, float)) and support > 0 and close_price < support:
            sr_interaction = "BREAKING_BELOW_SUPPORT"
        elif pivot and isinstance(pivot, (int, float)) and pivot > 0 and abs(close_price - pivot) <= threshold:
            sr_interaction = "TESTING_PIVOT"
        elif resistance and isinstance(resistance, (int, float)) and resistance > 0 and abs(close_price - resistance) <= threshold:
            sr_interaction = "TESTING_RESISTANCE"
        elif support and isinstance(support, (int, float)) and support > 0 and abs(close_price - support) <= threshold:
            sr_interaction = "TESTING_SUPPORT"
        else:
            sr_interaction = "NONE"

        # rejection_zone - FIXED: Calculate after sr_interaction
        if pivot and isinstance(pivot, (int, float)) and pivot > 0 and abs(close_price - pivot) <= threshold:
            rejection_zone = "AT_PIVOT"
        elif support and isinstance(support, (int, float)) and support > 0 and abs(close_price - support) <= threshold:
            rejection_zone = "AT_SUPPORT"
        elif resistance and isinstance(resistance, (int, float)) and resistance > 0 and abs(close_price - resistance) <= threshold:
            rejection_zone = "AT_RESISTANCE"
        else:
            rejection_zone = "NONE"

        # trap_alert mapping - FIXED: Use uppercase to match trap_detector output
        trap_detected = trap_data['trap_detected']
        trap_type = str(trap_data.get('trap_type', '')).upper()
        trap_alert = "NONE"
        if trap_detected:
            if trap_type in ('BULL_TRAP', 'BEAR_TRAP', 'STOP_HUNT', 'REJECTION'):
                trap_alert = trap_type
            else:
                trap_alert = "NONE"

        results['price_action'] = {
            'pattern': patterns[0] if patterns else 'NONE',
            'last_candle_bias': candle_data['last_candle_color'],
            'last_candle': candle_data['last_candle_color'],
            'body_strength': 'STRONG' if body_size > 0.1 else 'WEAK',
            'rejection_zone': rejection_zone,
            'wick_dominance': wick_dominance,
            'momentum_bias': pa_data['directional_bias'],
            'move_quality': pa_data['move_type'],
            'trap_alert': trap_alert,
            'sr_interaction': sr_interaction,
            'volume_momentum': pa_data['volume_momentum'],
            'divergence_alert': divergence_data.get('divergence_type', 'NONE'),
            'divergence_strength': divergence_data.get('divergence_strength', 0),
            'market_behavior': behavior_data.get('behavior', 'NEUTRAL'),
            'hesitation_score': behavior_data.get('hesitation', 50),
            'path_efficiency': efficiency_data.get('movement_quality', 'FAIR'),
        }

        results['advanced_signals'] = {
            'conflict_score': conflict_data.get('conflict_score', 0),
            'continuation_probability': continuation_data.get('continuation_probability', 50),
            'transition_risk': transition_data.get('transition_risk', 'LOW'),
            'persistence_score': persistence_data.get('persistence_score', 50),
            'is_persistent': persistence_data.get('is_persistent', False),
            'efficiency_score': efficiency_data.get('overall_efficiency', 50),
        }
            
        # Store individual specialized analyzer outputs
        results['behavior'] = behavior_data
        results['candle_pattern'] = candle_data
        results['trap_detector'] = trap_data
        results['conflict'] = conflict_data
        results['continuation'] = continuation_data
        results['divergence'] = divergence_data
        results['efficiency'] = efficiency_data
        results['persistence'] = persistence_data
        results['transition'] = transition_data

        return results
