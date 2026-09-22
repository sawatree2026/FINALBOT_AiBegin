"""MACD confirmation for Believe."""

from typing import Dict

from .field_utils import number


def evaluate(fields: Dict[str, str], action: str) -> bool:
    macd = number(fields, "s30_macd", "m1_macd")
    signal = number(fields, "s30_macd_signal", "m1_macd_signal")
    histogram = number(fields, "s30_macd_histogram", "m1_macd_histogram")
    if macd is None or signal is None:
        return False
    aligned = macd >= signal if action == "CALL" else macd <= signal
    if histogram is not None:
        aligned = aligned and (histogram >= 0 if action == "CALL" else histogram <= 0)
    return aligned
