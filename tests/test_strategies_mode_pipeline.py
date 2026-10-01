import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from data_decision.strategies_mode.believe_strategies.believe_analyzer import (
    analyze_payload_file,
)
from data_decision.strategies_mode.believe_strategies.bollinger_percent import (
    evaluate as evaluate_bollinger,
)
from data_decision.strategies_mode.decision_manager import DecisionManager
from data_evaluate.strategies_mode.orchestrator import Orchestrator
from data_trade.strategies_mode.execution_gate.gate_controller import ExecutionGate


class StrategiesPayloadTests(unittest.TestCase):
    def analyze(self, extra_fields=""):
        payload = f"""ID:SYNTHETIC
meta:
  mode: strategies
  expiry_minutes: 5
s30:
  bias: BULLISH
  is_doji: FALSE
  is_gray_candle: FALSE
  bb_percent_b: 0.08
  bb_percent_touch: LOWER
  sto_k: 52
  sto_d: 48
  sto_zone: NEUTRAL
  sto_cross: GOLDEN_CROSS
  sto_cross_50: TRUE
  sto_cross_50_direction: UP
  sto_hook_confirmed: TRUE
  sto_touch_low: TRUE
  sto_touch_high: FALSE
  sto_tangled: FALSE
  ma_cross: GOLDEN_CROSS
  ma_cross_confirmed: TRUE
  macd: -0.001
  macd_signal: -0.002
  macd_histogram: 0.001
  divergence_alert: STO_BULLISH
  rsi: 55
m1:
  grid_block_ahead: FALSE
  sr_block_call: FALSE
  sr_block_put: FALSE
  prev_candle_bad: FALSE
m15_window:
  doji_present: FALSE
  gray_candle_present: FALSE
{extra_fields}"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as handle:
            handle.write(payload)
            path = handle.name
        try:
            return analyze_payload_file("SYNTHETIC", path)
        finally:
            os.unlink(path)

    def test_raw_single_pass_payload_is_consumable(self):
        decision = self.analyze()
        self.assertEqual(decision["action"], "CALL")
        self.assertEqual(decision["expiry_minutes"], 5)
        self.assertEqual(decision["m5_direction"], "NOT_USED_BY_BELIEVE")

    def test_wrong_direction_stochastic_cross_is_rejected(self):
        decision = self.analyze("  sto_cross_50_direction: DOWN\n")
        self.assertEqual(decision["action"], "WAIT")

    def test_bollinger_threshold_uses_documented_limits(self):
        self.assertFalse(
            evaluate_bollinger(
                {"believe_bb_percent_b": "0.15", "believe_bb_touch": "NONE"},
                "CALL",
            )
        )
        self.assertFalse(
            evaluate_bollinger(
                {"believe_bb_percent_b": "0.85", "believe_bb_touch": "NONE"},
                "PUT",
            )
        )

    def test_gray_or_doji_blocks_entry(self):
        decision = self.analyze("  is_doji: TRUE\n")
        self.assertEqual(decision["action"], "WAIT")

    def test_strategy_expiry_is_five_minutes(self):
        result = ExecutionGate({}).evaluate_decision(
            "SYNTHETIC",
            {
                "mode": "strategies_mode",
                "action": "CALL",
                "expiry_minutes": 5,
                "confidence_score": 75,
                "conditions_met": True,
            },
        )
        self.assertTrue(result["approved"])

    def test_active_calculation_needs_only_s30_and_m1(self):
        index = pd.date_range("2026-01-01", periods=260, freq="30s", tz="UTC")
        closes = pd.Series(range(1000, 1260), index=index, dtype=float)
        s30 = pd.DataFrame(
            {
                "open": closes - 0.1,
                "high": closes + 0.2,
                "low": closes - 0.2,
                "close": closes,
                "volume": 1.0,
            },
            index=index,
        )
        m1 = pd.DataFrame(
            {
                "open": closes - 0.1,
                "high": closes + 0.2,
                "low": closes - 0.2,
                "close": closes,
                "volume": 1.0,
            },
            index=index,
        )
        orchestrator = object.__new__(Orchestrator)
        payload = orchestrator._calculate_single_pass(
            "SYNTHETIC", {"S30": s30, "M1": m1}
        )
        self.assertIn("bb_percent_period: 41", payload["raw_payload_text"])
        self.assertIn("sto_k:", payload["raw_payload_text"])
        self.assertIn("holding_period: 5m", payload["raw_payload_text"])
        self.assertNotIn("m5_stoch", payload["raw_payload_text"].lower())
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as handle:
            handle.write(payload["raw_payload_text"])
            path = handle.name
        try:
            decision = analyze_payload_file("SYNTHETIC", path)
            self.assertEqual(decision["expiry_minutes"], 5)
        finally:
            os.unlink(path)


class CycleIsolationTests(unittest.TestCase):
    def test_failed_evaluations_are_not_returned_as_ready(self):
        orchestrator = object.__new__(Orchestrator)

        def process_cycle(symbol):
            if symbol == "BAD":
                raise ValueError("synthetic offline failure")
            return {"txt_filepath": "synthetic"}

        orchestrator.process_cycle = process_cycle
        with patch("data_evaluate.strategies_mode.orchestrator.ConsoleUI.show_payload_export"):
            self.assertEqual(
                set(orchestrator.evaluate_cycle(["GOOD", "BAD"])),
                {"GOOD"},
            )

    def test_missing_payload_skips_symbol_without_aborting_decisions(self):
        manager = object.__new__(DecisionManager)
        manager._processed = set()
        with patch.object(DecisionManager, "_latest_payload", return_value=None):
            self.assertEqual(manager.process_latest(["NO_PAYLOAD"]), [])


if __name__ == "__main__":
    unittest.main()
