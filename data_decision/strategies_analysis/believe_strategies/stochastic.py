"""Stochastic component of Believe."""

from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    k = number(fields, "believe_sto_k")
    d = number(fields, "believe_sto_d")
    zone = text(fields, "believe_sto_zone")
    cross = text(fields, "believe_sto_cross")
    reversal = boolean(fields, "believe_sto_hook_confirmed")
    reversal = reversal or boolean(fields, "believe_sto_cross_50")
    reversal = reversal or cross in ({"UP", "BULLISH", "CALL", "BUY"} if action == "CALL" else {"DOWN", "BEARISH", "PUT", "SELL"})
    extreme = ("OVERSOLD" in zone and action == "CALL") or ("OVERBOUGHT" in zone and action == "PUT")
    extreme = extreme or (
        (action == "CALL" and min(k, d) <= 10) or (action == "PUT" and max(k, d) >= 90)
    )
    return extreme and reversal and not boolean(fields, "believe_risk_sto_tangled")
