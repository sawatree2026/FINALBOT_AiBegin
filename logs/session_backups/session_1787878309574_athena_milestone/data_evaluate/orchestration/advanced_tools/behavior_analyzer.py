"""
TIER 5 - BEHAVIOR ANALYZER


Combined behavioral intelligence engine.
Reads raw candle data and summarizes overall market "behavior":
participation, conviction, hesitation, and pressure balance.

This is a synthesis-style engine within Tier 5: it does NOT classify
market state or emit signals — it only describes how price is behaving.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

from data_evaluate.orchestration.base_engine import BaseEngine


class BehaviorAnalyzer(BaseEngine):
    """Tier 5: Combined Market Behavior Analyzer"""

    ENGINE_NAME = "behavior_analyzer"
    ENGINE_VERSION = "1.0.0"
    TIER = 5
    MIN_CANDLES = 40

    def get_neutral_state(self) -> Dict[str, Any]:
        return {
            'participation': 'LOW',
            'conviction': 'NEUTRAL',
            'hesitation': 'HIGH',
            'pressure_balance': 'BALANCED'
        }

    def _analyze(self, candles_df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        recent = candles_df.tail(30)

        conviction = self._conviction(recent)
        hesitation = self._hesitation(recent)
        pressure = self._pressure_balance(recent)
        participation = self._participation(recent)

        # Overall behavior label
        behavior = self._classify(conviction, hesitation, pressure)

        return {
            'conviction': conviction,                 # 0-100, how decisive candles are
            'hesitation': hesitation,                 # 0-100, how indecisive
            'pressure_balance': float(pressure),      # -100..+100 (buy vs sell)
            'participation': participation,           # 0-100, volume engagement
            'behavior': behavior,                     # text label
            'is_decisive': conviction > 60 and hesitation < 40,
            'confidence': 70,
        }

    def _conviction(self, df: pd.DataFrame) -> int:
        """Average body-to-range ratio — large bodies = conviction."""
        rng = (df['high'] - df['low']).replace(0, 1e-6)
        body = (df['close'] - df['open']).abs()
        ratio = (body / rng).mean()
        return int(min(100, max(0, ratio * 100)))

    def _hesitation(self, df: pd.DataFrame) -> int:
        """Share of small-body (doji-like) candles — hesitation."""
        rng = (df['high'] - df['low']).replace(0, 1e-6)
        body = (df['close'] - df['open']).abs()
        ratio = body / rng
        doji_share = float((ratio < 0.25).mean())
        return int(min(100, max(0, doji_share * 100)))

    def _pressure_balance(self, df: pd.DataFrame) -> float:
        """Net buying vs selling pressure based on Net Range."""
        bull = df.loc[df['close'] > df['open']].apply(lambda r: r['close'] - r['open'], axis=1).sum()
        bear = df.loc[df['close'] < df['open']].apply(lambda r: r['open'] - r['close'], axis=1).sum()
        total = bull + bear
        if total == 0:
            return 0.0
        return float(((bull - bear) / total) * 100)

    def _participation(self, df: pd.DataFrame) -> int:
        """Recent volume vs its baseline average — engagement level."""
        if 'volume' not in df.columns or df['volume'].sum() == 0:
            return 50  # Neutral participation when no volume data (e.g. OTC or market closed)
        if len(df) <= 5:
            return 50
        baseline_df = df.iloc[:-5]
        avg = baseline_df['volume'].mean()
        recent = df['volume'].tail(5).mean()
        if avg == 0 or pd.isna(avg):
            return 50
        return int(min(100, max(0, (recent / avg) * 50)))

    def _classify(self, conviction: int, hesitation: int,
                  pressure: float) -> str:
        if conviction > 60:
            return 'DECISIVE_BUYING' if pressure > 15 else \
                   'DECISIVE_SELLING' if pressure < -15 else 'DECISIVE_MIXED'
                   
        # Check for creeping trends (high consistent pressure despite low conviction)
        if abs(pressure) > 60:
            return 'CREEPING_BUYING' if pressure > 0 else 'CREEPING_SELLING'
            
        if hesitation > 55:
            return 'INDECISIVE'
            
        return 'NEUTRAL'

