"""Stochastic component of Believe — NEMESIS E-BOOK V2 p.37 / p.49."""

from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    k = number(fields, "believe_sto_k")
    d = number(fields, "believe_sto_d")
    zone = text(fields, "believe_sto_zone") if "believe_sto_zone" in fields else ""
    cross = text(fields, "believe_sto_cross") if "believe_sto_cross" in fields else "NONE"
    hook = boolean(fields, "believe_sto_hook_confirmed") if "believe_sto_hook_confirmed" in fields else False
    cross_50 = boolean(fields, "believe_sto_cross_50") if "believe_sto_cross_50" in fields else False
    tangled = boolean(fields, "believe_risk_sto_tangled") if "believe_risk_sto_tangled" in fields else False

    if tangled:
        return False

    # Nemesis V.2 Rule (p.37, 44, 49):
    # CALL: STO must touch 10 (OVERSOLD_10) and reverse (hook up, cross 50, or K cross D up)
    # PUT: STO must touch 90 (OVERBOUGHT_90) and reverse (hook down, cross 50, or K cross D down)
    if action == "CALL":
        has_touched = ("10" in zone or "OVERSOLD" in zone or k <= 15.0 or boolean(fields, "believe_sto_touch_low") if "believe_sto_touch_low" in fields else (k <= 15.0 or "10" in zone))
        has_reversed = hook or cross_50 or cross in {"GOLDEN_CROSS", "UP", "BULLISH", "CALL"} or (k > d and k > 10.0)
        return has_touched and has_reversed

    if action == "PUT":
        has_touched = ("90" in zone or "OVERBOUGHT" in zone or k >= 85.0 or boolean(fields, "believe_sto_touch_high") if "believe_sto_touch_high" in fields else (k >= 85.0 or "90" in zone))
        has_reversed = hook or cross_50 or cross in {"DEATH_CROSS", "DOWN", "BEARISH", "PUT"} or (k < d and k < 90.0)
        return has_touched and has_reversed

    return False
