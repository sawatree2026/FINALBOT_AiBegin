"""
FINALBOT Central Mode Dispatcher (mode_loader.py)
Single Source of Truth for loading and dispatching all 4 Parts per active mode.
"""

import os
import sys
import types
import importlib.util
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


def _install_mode_namespace(mode: str) -> None:
    """Route data_evaluate.orchestration to the active mode's orchestration folder."""
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mode_root = os.path.join(workspace_root, "data_evaluate", mode)

    for name in ("data_evaluate.orchestration",):
        for loaded in list(sys.modules):
            if loaded == name or loaded.startswith(f"{name}."):
                del sys.modules[loaded]
        package = types.ModuleType(name)
        orch_dir = os.path.join(mode_root, "orchestration")
        if os.path.isdir(orch_dir):
            package.__path__ = [orch_dir]
            package.__package__ = name
            sys.modules[name] = package

    for mod in ("exceptions", "news_calendar"):
        full_name = f"data_evaluate.{mod}"
        src = os.path.join(mode_root, f"{mod}.py")
        if os.path.isfile(src):
            spec = importlib.util.spec_from_file_location(full_name, src)
            if spec and spec.loader:
                m = importlib.util.module_from_spec(spec)
                sys.modules[full_name] = m
                spec.loader.exec_module(m)


def load_broker_adapter(mode: Any, settings: Dict[str, Any]) -> Any:
    """Load the dedicated broker adapter (Bridge) for the active mode."""
    norm = normalize_mode(mode)
    if norm == "strategies_mode":
        from data_feed.strategies_mode.bridge_adapter.broker_factory import BrokerFactory
        return BrokerFactory.create_raw_broker(config=settings)
    elif norm in ("ml_mode", "ai_mode"):
        from data_feed.ai_mode.bridge_adapter.broker_factory import BrokerFactory
        return BrokerFactory.create_raw_broker(config=settings)
    raise ValueError(f"FAIL-FAST: Cannot load broker adapter for unknown mode {norm}")


def load_data_feed(mode: Any, settings: Dict[str, Any], broker_adapter: Any = None) -> Any:
    """Part 1: Load DataAdapter for the active mode."""
    norm = normalize_mode(mode)
    feed_dir = mode_feed_dir(settings, norm)
    settings.setdefault("data_feed", {}).setdefault("csv_manager", {})["base_dir"] = feed_dir
    if norm == "strategies_mode":
        from data_feed.strategies_mode.data_adapter import DataAdapter
        return DataAdapter(config=settings, broker_adapter=broker_adapter)
    elif norm in ("ml_mode", "ai_mode"):
        workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        feed_root = os.path.join(workspace_root, "data_feed", "ai_mode")
        if (
            "data_feed" not in sys.modules
            or not hasattr(sys.modules["data_feed"], "__path__")
            or sys.modules["data_feed"].__path__ != [feed_root]
        ):
            for loaded in list(sys.modules):
                if loaded == "data_feed" or loaded.startswith("data_feed."):
                    del sys.modules[loaded]
            package = types.ModuleType("data_feed")
            package.__path__ = [feed_root]
            package.__package__ = "data_feed"
            sys.modules["data_feed"] = package
        from data_feed.data_adapter import DataAdapter
        return DataAdapter(config=settings, broker_adapter=broker_adapter)
    raise ValueError(f"FAIL-FAST: Cannot load DataAdapter for unknown mode {norm}")


def mode_feed_dir(settings: Dict[str, Any], mode: Any) -> str:
    """Get the feed output directory under data_base/{mode}/output_feed."""
    norm = normalize_mode(mode)
    return os.path.join("data_base", norm, "output_feed")


def mode_output_dir(settings: Dict[str, Any], mode: Any) -> str:
    """Get the evaluation output directory under data_base/{mode}/output_evaluate."""
    norm = normalize_mode(mode)
    mode_dirs = settings.get("data_evaluate", {}).get("mode_output_dirs", {})
    if norm in mode_dirs:
        return mode_dirs[norm]
    return os.path.join("data_base", norm, "output_evaluate")


def mode_decision_dir(settings: Dict[str, Any], mode: Any) -> str:
    """Get the decision output directory under data_base/{mode}/output_decision."""
    norm = normalize_mode(mode)
    return os.path.join("data_base", norm, "output_decision")


def mode_trade_dir(settings: Dict[str, Any], mode: Any) -> str:
    """Get the trade output directory under data_base/{mode}/output_trade."""
    norm = normalize_mode(mode)
    return os.path.join("data_base", norm, "output_trade")


def load_orchestrator(mode: Any, settings: Dict[str, Any]) -> Any:
    """Part 2: Load Evaluation Orchestrator for the active mode."""
    norm = normalize_mode(mode)
    _install_mode_namespace(norm)
    eval_dir = mode_output_dir(settings, norm)
    settings.setdefault("data_evaluate", {})["output_dir"] = eval_dir
    if norm == "strategies_mode":
        from data_evaluate.strategies_mode.orchestrator import Orchestrator
        return Orchestrator(settings)
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
    dec_dir = mode_decision_dir(settings, norm)
    settings.setdefault("data_decision", {})["output_dir"] = dec_dir
    if norm in ("strategies_mode", "ml_mode", "ai_mode"):
        from data_decision.strategies_mode.decision_manager import DecisionManager
        return DecisionManager(settings)
    raise ValueError(f"FAIL-FAST: Cannot load DecisionManager for unknown mode {norm}")


def load_executor_manager(mode: Any, settings: Dict[str, Any], broker_adapter: Any = None) -> Any:
    """Part 4: Load ExecutorManager for the active mode with single broker binding."""
    norm = normalize_mode(mode)
    trade_dir = mode_trade_dir(settings, norm)
    settings.setdefault("data_trade", {})["trade_history_file"] = os.path.join(
        trade_dir, "trades_history.csv"
    )
    if norm in ("strategies_mode", "ml_mode", "ai_mode"):
        from data_trade.strategies_mode.executor_manager import ExecutorManager
        mgr = ExecutorManager(settings)
        if broker_adapter is not None:
            mgr._broker_adapter = broker_adapter
        return mgr
    raise ValueError(f"FAIL-FAST: Cannot load ExecutorManager for unknown mode {norm}")
