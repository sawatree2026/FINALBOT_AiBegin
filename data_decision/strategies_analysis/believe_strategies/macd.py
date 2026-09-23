"""MACD confirmation for Believe."""

from typing import Dict

from .field_utils import number


def evaluate(fields: Dict[str, str], action: str) -> bool:
    macd = number(fields, "m1_macd")
    signal = number(fields, "m1_macd_signal")
    histogram = number(fields, "m1_macd_histogram")
    if action == "CALL":
        return macd < 0 and macd >= signal and histogram >= 0
    return macd > 0 and macd <= signal and histogram <= 0
