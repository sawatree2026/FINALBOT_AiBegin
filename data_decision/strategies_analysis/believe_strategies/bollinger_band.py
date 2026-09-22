"""Bollinger Band component of Believe."""

from typing import Dict

from .field_utils import number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    percent_b = number(fields, "believe_bb_percent_b", "s30_bb_percent_b", "m1_bb_percent_b")
    touch = text(fields, "believe_bb_touch", "s30_bb_touch", "m1_bb_touch")
    if action == "CALL":
        return touch in {"LOWER", "LOWER_0", "LOWER_BAND"} or (
            percent_b is not None and percent_b <= 0.15
        )
    if action == "PUT":
        return touch in {"UPPER", "UPPER_1", "UPPER_BAND"} or (
            percent_b is not None and percent_b >= 0.85
        )
    return False
