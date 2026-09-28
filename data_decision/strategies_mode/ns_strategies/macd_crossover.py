"""MACD Near-Crossover module for NS Strategy (Nemesis V.2 3.3)."""
from typing import Dict

def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        return False
    macd_cross = fields.get("macd_cross", fields.get("s30_macd_cross", "NONE")).upper()
    macd_zero = fields.get("macd_zero_cross", fields.get("s30_macd_zero_cross", "NONE")).upper()
    
    if action == "CALL":
        return macd_cross in {"BULLISH", "GOLDEN_CROSS", "UP"} or macd_zero == "ABOVE"
    if action == "PUT":
        return macd_cross in {"BEARISH", "DEATH_CROSS", "DOWN"} or macd_zero == "BELOW"
    return False
