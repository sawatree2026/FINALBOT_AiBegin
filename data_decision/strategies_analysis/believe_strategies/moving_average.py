"""Moving Average component of Believe."""

from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    cross = text(fields, "believe_ma_cross")
    expected = {"GOLDEN_CROSS", "UP", "BULLISH", "CALL", "BUY"} if action == "CALL" else {
        "DEATH_CROSS", "DOWN", "BEARISH", "PUT", "SELL"
    }
    if cross in expected and boolean(fields, "believe_ma_cross_confirmed"):
        return True
    fast = number(fields, "believe_ma_fast")
    slow = number(fields, "believe_ma_slow")
    return fast > slow if action == "CALL" else fast < slow
