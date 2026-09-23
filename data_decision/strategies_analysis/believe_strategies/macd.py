"""MACD confirmation for Believe."""

from typing import Dict

from .field_utils import number


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    macd = number(fields, "s30_macd")
    signal = number(fields, "s30_macd_signal")
    histogram = number(fields, "s30_macd_histogram")
    aligned = macd >= signal if action == "CALL" else macd <= signal
    return aligned and (histogram >= 0 if action == "CALL" else histogram <= 0)
