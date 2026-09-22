"""Stochastic component of Believe."""

from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    k = number(fields, "believe_sto_k", "m1_stoch_k")
    d = number(fields, "believe_sto_d", "m1_stoch_d")
    zone = text(fields, "believe_sto_zone", "m1_stoch_zone")
    cross = text(fields, "believe_sto_cross", "m1_stoch_cross")
    reversal = boolean(fields, "believe_sto_hook_confirmed", "m1_stoch_hook_confirmed") is True
    reversal = reversal or boolean(fields, "believe_sto_cross_50", "m1_stoch_cross_50") is True
    reversal = reversal or cross in ({"UP", "BULLISH", "CALL", "BUY"} if action == "CALL" else {"DOWN", "BEARISH", "PUT", "SELL"})
    extreme = ("OVERSOLD" in zone and action == "CALL") or ("OVERBOUGHT" in zone and action == "PUT")
    extreme = extreme or (k is not None and d is not None and (
        (action == "CALL" and min(k, d) <= 10) or (action == "PUT" and max(k, d) >= 90)
    ))
    return extreme and reversal and boolean(fields, "believe_sto_tangled", "m1_stoch_tangled") is not True
