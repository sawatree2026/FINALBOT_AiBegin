"""RSI safety confirmation for Believe."""

from typing import Dict

from .field_utils import number


def evaluate(fields: Dict[str, str], action: str) -> bool:
    value = number(fields, "s30_rsi", "m1_rsi")
    return value is not None and (value >= 30 if action == "CALL" else value <= 70)
