"""Candle and Price Action confirmation for Believe."""

from typing import Dict

from .field_utils import text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    pattern = text(fields, "m5_pa_pattern", "pa_pattern")
    bias = text(fields, "m5_pa_last_candle_bias", "pa_last_candle_bias")
    bullish = {"ENGULFING_BULLISH", "HAMMER", "GR_UP", "BULLISH"}
    bearish = {"ENGULFING_BEARISH", "SHOOTING_STAR", "RG_DOWN", "BEARISH"}
    return pattern in (bullish if action == "CALL" else bearish) or bias in (
        {"BULLISH", "UP", "CALL", "BUY"} if action == "CALL" else {"BEARISH", "DOWN", "PUT", "SELL"}
    )
