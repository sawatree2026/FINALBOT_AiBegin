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
    # เชื่อมโยงจังหวะแตะ 10/90 กับการข้ามผ่าน 50 โดยไม่จำกัดเฉพาะแท่งที่แตะ 50 เป๊ะ
    if action == "CALL":
        cross_50_ok = (cross_50_direction == "UP") or (k >= 45.0 and (hook or k > d))
        return touch_low and cross_50_ok

    if action == "PUT":
        cross_50_ok = (cross_50_direction == "DOWN") or (k <= 55.0 and (hook or k < d))
        return touch_high and cross_50_ok

    return False
