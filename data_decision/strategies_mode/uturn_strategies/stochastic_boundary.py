"""Stochastic Boundary module for U-Turn Strategy (Nemesis V.2 3.4 - STO 13,10,3)."""
from typing import Dict

def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        return False
    sto_k = float(fields.get("sto_k", fields.get("believe_sto_k", 50.0)))
    sto_zone = fields.get("sto_zone", fields.get("believe_sto_zone", "NONE")).upper()
    
    if action == "CALL":
        return sto_k <= 15.0 or "OVERSOLD" in sto_zone or "10" in sto_zone
    if action == "PUT":
        return sto_k >= 85.0 or "OVERBOUGHT" in sto_zone or "90" in sto_zone
    return False
