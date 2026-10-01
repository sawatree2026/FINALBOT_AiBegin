"""Bollinger Band component of Believe (Nemesis E-Book 3.5)."""

import math
from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    percent_b = number(fields, "believe_bb_percent_b")
    if not math.isfinite(percent_b):
        raise ValueError("Invalid numeric Believe payload field: believe_bb_percent_b")

    touch = text(fields, "believe_bb_touch").upper()
    has_touch_low = (
        boolean(fields, "believe_bb_touch_low") if "believe_bb_touch_low" in fields
        else (boolean(fields, "bb_touch_low") if "bb_touch_low" in fields else False)
    )
    has_touch_high = (
        boolean(fields, "believe_bb_touch_high") if "believe_bb_touch_high" in fields
        else (boolean(fields, "bb_touch_high") if "bb_touch_high" in fields else False)
    )
    touch_low = has_touch_low or touch in {"LOWER", "LOWER_0", "LOWER_BAND"} or percent_b <= 0.0
    touch_high = has_touch_high or touch in {"UPPER", "UPPER_1", "UPPER_BAND"} or percent_b >= 1.0

    # Nemesis Believe Rule (E-Book V.2 p.37, 38, 49):
    # BB% (Bollinger Bands %B) ต้องแตะเส้น 0 (CALL) หรือเส้น 1 (PUT) ก่อนเสมอ
    if action == "CALL":
        return touch_low
    if action == "PUT":
        return touch_high
    return False
