"""Support & Resistance Bounce module for U-Turn Strategy (Nemesis V.2 3.4)."""
from typing import Dict

def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        return False
    sr_clear = fields.get("support_resistance_clear", fields.get("sr_clear", "TRUE")).upper() in {"TRUE", "1", "YES"}
    sr_interaction = fields.get("sr_type", fields.get("m5_pa_sr_interaction", "NONE")).upper()
    
    if action == "CALL":
        return sr_clear or sr_interaction in {"BOUNCE_SUPPORT", "TOUCH_SUPPORT"}
    if action == "PUT":
        return sr_clear or sr_interaction in {"BOUNCE_RESISTANCE", "TOUCH_RESISTANCE"}
    return False
