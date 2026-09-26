"""Stochastic component of Believe."""

from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    k = number(fields, "believe_sto_k")
    d = number(fields, "believe_sto_d")
    zone = text(fields, "believe_sto_zone")
    cross = text(fields, "believe_sto_cross")
    reversal = boolean(fields, "believe_sto_hook_confirmed")
    reversal = reversal or boolean(fields, "believe_sto_cross_50")
    reversal = reversal or cross in ({"UP", "BULLISH", "CALL", "BUY"} if action == "CALL" else {"DOWN", "BEARISH", "PUT", "SELL"})
    extreme = (
        ("OVERSOLD" in zone or "10" in zone or min(k, d) <= 35)
        if action == "CALL"
        else ("OVERBOUGHT" in zone or "90" in zone or max(k, d) >= 65)
    )
    return (extreme or reversal) and not boolean(fields, "believe_risk_sto_tangled")
