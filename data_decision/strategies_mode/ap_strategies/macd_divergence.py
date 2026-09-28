"""MACD and RSI Divergence module for AP Strategy (Nemesis V.2 3.2)."""
from typing import Dict
from .field_utils import text

def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        return False
    div_alert = fields.get("divergence_alert", fields.get("m5_pa_divergence_alert", "NONE")).upper()
    if action == "CALL":
        return "BULLISH" in div_alert or div_alert in {"RSI_BULLISH", "MACD_BULLISH"}
    if action == "PUT":
        return "BEARISH" in div_alert or div_alert in {"RSI_BEARISH", "MACD_BEARISH"}
    return False
