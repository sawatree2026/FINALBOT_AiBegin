"""Load the evaluation implementation selected by the active runtime mode."""

import importlib.util
import os
import sys
import types
from typing import Any, Dict

VALID_MODES = ("ml_mode", "ai_mode", "strategies_mode")


def normalize_evaluate_mode(value: Any) -> str:
    mode = str(value or "ml_mode").strip().lower()
    aliases = {
        "ml": "ml_mode",
        "ai": "ai_mode",
        "strategies": "strategies_mode",
        "strategy": "strategies_mode",
    }
    mode = aliases.get(mode, mode)
    if mode not in VALID_MODES:
        raise ValueError(
            f"FAIL-FAST: Unsupported evaluation mode {value!r}; "
            f"expected one of {', '.join(VALID_MODES)}"
        )
    return mode


def load_orchestrator_class(mode: Any) -> type:
    """Load ``data_evaluate/<mode>/orchestrator.py`` without sharing module state."""
    normalized = normalize_evaluate_mode(mode)
    _install_mode_namespace(normalized)
    path = os.path.join(os.path.dirname(__file__), normalized, "orchestrator.py")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"FAIL-FAST: Evaluation orchestrator not found: {path}")

    module_name = f"finalbot_evaluate_{normalized}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"FAIL-FAST: Cannot load evaluation orchestrator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    orchestrator = getattr(module, "Orchestrator", None)
    if orchestrator is None:
        raise ImportError(f"FAIL-FAST: Orchestrator class missing from {path}")
    return orchestrator


def _install_mode_namespace(mode: str) -> None:
    """Route the mode's absolute ``data_evaluate.*`` imports to its folder."""
    mode_root = os.path.join(os.path.dirname(__file__), mode)
    for name in ("data_evaluate.orchestration",):
        for loaded in list(sys.modules):
            if loaded == name or loaded.startswith(f"{name}."):
                del sys.modules[loaded]
        package = types.ModuleType(name)
        package.__path__ = [os.path.join(mode_root, "orchestration")]
        package.__package__ = name
        sys.modules[name] = package

    for module_name in ("exceptions", "news_calendar"):
        full_name = f"data_evaluate.{module_name}"
        source = os.path.join(mode_root, f"{module_name}.py")
        spec = importlib.util.spec_from_file_location(full_name, source)
        if spec is None or spec.loader is None:
            raise ImportError(f"FAIL-FAST: Cannot load mode module: {source}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)


def mode_output_dir(settings: Dict[str, Any], mode: Any) -> str:
    normalized = normalize_evaluate_mode(mode)
    mode_dirs = settings.get("data_evaluate", {}).get("mode_output_dirs", {})
    if normalized in mode_dirs:
        return mode_dirs[normalized]
    configured_root = settings.get("data_evaluate", {}).get(
        "output_dir", os.path.join("data_base", "output_evaluate")
    )
    return os.path.join(configured_root, normalized)
