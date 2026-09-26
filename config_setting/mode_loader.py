"""
FINALBOT Central Mode Dispatcher (mode_loader.py)
Single Source of Truth for loading and dispatching all 4 Parts per active mode.
"""

import os
import sys
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("mode_loader")

VALID_MODES = ("strategies_mode", "ml_mode", "ai_mode")

MODE_ALIASES = {
    "strategies": "strategies_mode",
    "strategy": "strategies_mode",
    "strategies_mode": "strategies_mode",
    "ml": "ml_mode",
    "ml_mode": "ml_mode",
    "ai": "ai_mode",
    "ai_mode": "ai_mode",
}


def normalize_mode(value: Any) -> str:
    """Normalize any mode alias string to one of the strict VALID_MODES."""
    mode_str = str(value or "strategies_mode").strip().lower()
    normalized = MODE_ALIASES.get(mode_str)
    if not normalized or normalized not in VALID_MODES:
        raise ValueError(
            f"FAIL-FAST: Unsupported mode {value!r}; "
            f"expected one of {', '.join(VALID_MODES)}"
        )
    return normalized


normalize_evaluate_mode = normalize_mode


def get_active_mode(settings: Optional[Dict[str, Any]] = None) -> str:
    """Read and normalize active_mode from settings.json."""
    if settings is None:
        from config_setting.config_loader import load_settings
        settings = load_settings(reload=False)
    raw_mode = settings.get("active_mode", "strategies_mode")
    return normalize_mode(raw_mode)


def load_broker_adapter(mode: Any, settings: Dict[str, Any]) -> Any:
    """Load the dedicated broker adapter (Bridge) for the active mode."""
    norm = normalize_mode(mode)
    if norm == "strategies_mode":
        from data_feed.strategies_mode.bridge_adapter.broker_factory import BrokerFactory
        return BrokerFactory.create_raw_broker(config=settings)
    elif norm == "ml_mode":
        from data_feed.ml_mode.bridge_adapter.broker_factory import BrokerFactory
        return BrokerFactory.create_raw_broker(config=settings)
    elif norm == "ai_mode":
        from data_feed.ai_mode.bridge_adapter.broker_factory import BrokerFactory
        return BrokerFactory.create_raw_broker(config=settings)
    raise ValueError(f"FAIL-FAST: Cannot load broker adapter for unknown mode {norm}")


def load_data_feed(mode: Any, settings: Dict[str, Any], broker_adapter: Any = None) -> Any:
    """Part 1: Load DataAdapter for the active mode."""
    norm = normalize_mode(mode)
    if norm == "strategies_mode":
        from data_feed.strategies_mode.data_adapter import DataAdapter
        return DataAdapter(config=settings, broker_adapter=broker_adapter)
    elif norm == "ml_mode":
        from data_feed.ml_mode.data_adapter import DataAdapter
        return DataAdapter(config=settings, broker_adapter=broker_adapter)
    elif norm == "ai_mode":
        from data_feed.ai_mode.data_adapter import DataAdapter
        return DataAdapter(config=settings, broker_adapter=broker_adapter)
    raise ValueError(f"FAIL-FAST: Cannot load DataAdapter for unknown mode {norm}")


def load_orchestrator(mode: Any, settings: Dict[str, Any]) -> Any:
    """Part 2: Load Evaluation Orchestrator for the active mode."""
    norm = normalize_mode(mode)
    if norm == "strategies_mode":
        from data_evaluate.strategies_mode.orchestrator import StrategiesOrchestrator
        return StrategiesOrchestrator(settings)
    elif norm == "ml_mode":
        from data_evaluate.ml_mode.orchestrator import Orchestrator
        return Orchestrator(settings)
    elif norm == "ai_mode":
        from data_evaluate.ai_mode.orchestrator import Orchestrator
        return Orchestrator(settings)
    raise ValueError(f"FAIL-FAST: Cannot load Orchestrator for unknown mode {norm}")


def load_decision_manager(mode: Any, settings: Dict[str, Any]) -> Any:
    """Part 3: Load DecisionManager for the active mode."""
    norm = normalize_mode(mode)
    if norm == "strategies_mode":
        from data_decision.strategies_mode.decision_manager import DecisionManager
        return DecisionManager(settings)
    elif norm == "ml_mode":
        from data_decision.ml_mode.decision_manager import DecisionManager
        return DecisionManager(settings)
    elif norm == "ai_mode":
        from data_decision.ai_mode.decision_manager import DecisionManager
        return DecisionManager(settings)
    raise ValueError(f"FAIL-FAST: Cannot load DecisionManager for unknown mode {norm}")


def load_executor_manager(mode: Any, settings: Dict[str, Any], broker_adapter: Any = None) -> Any:
    """Part 4: Load ExecutorManager for the active mode with single broker binding."""
    norm = normalize_mode(mode)
    if norm == "strategies_mode":
        from data_trade.strategies_mode.executor_manager import ExecutorManager
        mgr = ExecutorManager(settings)
        if broker_adapter is not None:
            mgr._broker_adapter = broker_adapter
        return mgr
    elif norm == "ml_mode":
        from data_trade.ml_mode.executor_manager import ExecutorManager
        mgr = ExecutorManager(settings)
        if broker_adapter is not None:
            mgr._broker_adapter = broker_adapter
        return mgr
    elif norm == "ai_mode":
        from data_trade.ai_mode.executor_manager import ExecutorManager
        mgr = ExecutorManager(settings)
        if broker_adapter is not None:
            mgr._broker_adapter = broker_adapter
        return mgr
    raise ValueError(f"FAIL-FAST: Cannot load ExecutorManager for unknown mode {norm}")


def mode_output_dir(settings: Dict[str, Any], mode: Any) -> str:
    """Get the evaluation output directory under data_base/output_evaluate/."""
    norm = normalize_mode(mode)
    mode_dirs = settings.get("data_evaluate", {}).get("mode_output_dirs", {})
    if norm in mode_dirs:
        return mode_dirs[norm]
    root = settings.get("data_evaluate", {}).get(
        "output_dir", os.path.join("data_base", "output_evaluate")
    )
    return os.path.join(root, norm)
