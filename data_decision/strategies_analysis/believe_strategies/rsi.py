"""RSI safety confirmation for Believe."""

from typing import Dict

from .field_utils import number


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    value = number(fields, "s30_rsi")
    return value >= 30 if action == "CALL" else value <= 70
