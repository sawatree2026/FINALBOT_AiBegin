"""Stochastic component of Believe — NEMESIS E-BOOK V2 p.37 / p.49."""

from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    k = number(fields, "believe_sto_k")
    d = number(fields, "believe_sto_d")
    zone = text(fields, "believe_sto_zone") if "believe_sto_zone" in fields else ""
    hook = boolean(fields, "believe_sto_hook_confirmed") if "believe_sto_hook_confirmed" in fields else False
    cross_50_direction = (
        text(fields, "believe_sto_cross_50_direction")
        if "believe_sto_cross_50_direction" in fields else "NONE"
    )
    tangled = boolean(fields, "believe_risk_sto_tangled") if "believe_risk_sto_tangled" in fields else False
    touch_low = (
        boolean(fields, "believe_sto_touch_low")
        if "believe_sto_touch_low" in fields else k <= 10.0
    )
    touch_high = (
        boolean(fields, "believe_sto_touch_high")
        if "believe_sto_touch_high" in fields else k >= 90.0
    )

    if tangled:
        return False

    # Nemesis V.2 Rule (p.37, 44, 49):
    # Believe requires a 10/90 touch, a directional hook, and a same-direction
    # crossing of 50; M5 stochastic is deliberately not consulted here.
    if action == "CALL":
        return touch_low and hook and cross_50_direction == "UP"

    if action == "PUT":
        return touch_high and hook and cross_50_direction == "DOWN"

    return False
