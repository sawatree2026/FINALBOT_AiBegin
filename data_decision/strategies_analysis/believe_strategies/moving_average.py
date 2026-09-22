"""Moving Average component of Believe."""

from typing import Dict

from .field_utils import boolean, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    cross = text(fields, "believe_ma_cross", "m1_ma_cross")
    expected = {"GOLDEN_CROSS", "UP", "BULLISH", "CALL", "BUY"} if action == "CALL" else {
        "DEATH_CROSS", "DOWN", "BEARISH", "PUT", "SELL"
    }
    return cross in expected and boolean(fields, "believe_ma_cross_confirmed", "m1_ma_cross_confirmed") is True
