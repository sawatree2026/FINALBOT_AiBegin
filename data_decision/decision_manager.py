"""Part 3 coordinator: read evaluation payloads and write decision files to SSD."""

import json
import logging
import os
import time
from typing import Any, Dict, Iterable, Optional

from config_setting.config_loader import load_settings
from data_decision.ai_analysis.artificial_intelligence.ai_dispatcher import SystemPrompt
from data_decision.strategies_analysis.believe_strategies.believe_analyzer import analyze_payload_file
from data_evaluate.mode_loader import mode_output_dir, normalize_evaluate_mode

logger = logging.getLogger("DecisionManager")


class DecisionManager:
    """Owns AI and strategy analysis; all Part 2/3/4 handoffs are files."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.settings = config or load_settings(reload=False)
        self.active_mode = normalize_evaluate_mode(self.settings.get("active_mode", "ml_mode"))
        self.evaluate_dir = mode_output_dir(self.settings, self.active_mode)
        decision_cfg = self.settings.get("data_decision", {})
        self.decision_dir = decision_cfg.get(
            "output_dir", os.path.join("data_base", "output_decision")
        )
        self.ai_dir = decision_cfg.get(
            "ai_output_dir", os.path.join(self.decision_dir, "ai_decision")
        )
        self.ml_dir = decision_cfg.get(
            "ml_output_dir", os.path.join(self.decision_dir, "ml_decision")
        )
        self.strategy_dir = decision_cfg.get(
            "strategies_output_dir", os.path.join(self.decision_dir, "strategies_decision")
        )
        self._processed: set[str] = set()

    def process_latest(self, symbols: Iterable[str]) -> list[str]:
        processed = []
        for symbol in symbols:
            payload_path = self._latest_payload(symbol)
            if not payload_path or payload_path in self._processed:
                continue
            self.process_payload_file(symbol, payload_path)
            self._processed.add(payload_path)
            processed.append(symbol)
        return processed

    def process_payload_file(self, symbol: str, payload_path: str) -> None:
        if not os.path.isfile(payload_path):
            raise FileNotFoundError(f"FAIL-FAST: Evaluation payload not found: {payload_path}")

        if self.active_mode == "ai_mode":
            decision = SystemPrompt.process_ai_decision(
                symbol=symbol, prompt_filepath=payload_path
            )
            root = self.ai_dir
        elif self.active_mode == "strategies_mode":
            decision = analyze_payload_file(symbol, payload_path)
            root = self.strategy_dir
        else:
            from data_decision.ai_analysis.machine_learning.ml_dispatcher import MLDispatcher
            decision = MLDispatcher.get_instance(self.settings).process_payload_file(
                symbol, prompt_filepath=payload_path
            )
            root = self.ml_dir

        payload_id = str(
            decision.get("ID") or os.path.basename(payload_path).split(".")[0]
        )
        decision = {
            **decision,
            "payload_id": payload_id,
            "payload_filepath": os.path.abspath(payload_path),
            "source_part": "data_evaluate",
            "mode": self.active_mode,
            "written_at": time.time(),
        }
        self._atomic_json(root, symbol, payload_id, decision)

    def _latest_payload(self, symbol: str) -> Optional[str]:
        symbol_dir = os.path.join(self.evaluate_dir, symbol)
        if not os.path.isdir(symbol_dir):
            return None
        files = [
            os.path.join(symbol_dir, name)
            for name in os.listdir(symbol_dir)
            if name.endswith(".txt") and os.path.isfile(os.path.join(symbol_dir, name))
        ]
        return max(files, key=os.path.getmtime) if files else None

    @staticmethod
    def _atomic_json(root: str, symbol: str, payload_id: str, decision: Dict[str, Any]) -> None:
        symbol_dir = os.path.join(root, symbol)
        os.makedirs(symbol_dir, exist_ok=True)
        target = os.path.join(symbol_dir, f"{payload_id}.json")
        temp = f"{target}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(decision, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
