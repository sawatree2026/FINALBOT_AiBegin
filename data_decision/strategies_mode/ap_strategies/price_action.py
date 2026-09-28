"""Price Action and Rejection module for AP Strategy (Nemesis V.2 3.2)."""
from typing import Dict
from .field_utils import text, boolean

def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        return False
    # Filter 1: Must not have gray candle
    gray_candle = fields.get("gray_candle_present", fields.get("pa_gray_candle", "FALSE")).upper() in {"TRUE", "1", "YES"}
    if gray_candle:
        return False
    
    # Filter 2: Rejection or Pattern Signal
    pa_pattern = fields.get("pa_pattern", fields.get("m5_pa_pattern", "NONE")).upper()
    pa_bias = fields.get("pa_bias", fields.get("m5_pa_last_candle_bias", "NEUTRAL")).upper()
    
    if action == "CALL":
        return pa_pattern in {"BULLISH_ENGULFING", "HAMMER", "REJECTION_UP"} or pa_bias == "BULLISH"
    if action == "PUT":
        return pa_pattern in {"BEARISH_ENGULFING", "SHOOTING_STAR", "REJECTION_DOWN"} or pa_bias == "BEARISH"
    return False
