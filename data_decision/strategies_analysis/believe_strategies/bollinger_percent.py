"""Bollinger Band component of Believe."""

import math
from typing import Dict

from .field_utils import number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    percent_b = number(fields, "believe_bb_percent_b")
    if not math.isfinite(percent_b):
        raise ValueError("Invalid numeric Believe payload field: believe_bb_percent_b")

    touch = text(fields, "believe_bb_touch")
    # Nemesis V.2 Rule (p.37): BB should touch 0 or 1, but doesn't have to ("จะไม่แตะก็ได้").
    # When MA crosses and STO crosses 50, price has already bounced into 0.20-0.45 (%B).
    if action == "CALL":
        return percent_b <= 0.45 or touch in {"LOWER", "LOWER_0", "LOWER_BAND", "NONE"}
    if action == "PUT":
        return percent_b >= 0.55 or touch in {"UPPER", "UPPER_1", "UPPER_BAND", "NONE"}
    return True
