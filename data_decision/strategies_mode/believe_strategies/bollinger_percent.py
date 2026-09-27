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
    # Nemesis Believe Rule: CALL must touch 0 (Lower Band), PUT must touch 1 (Upper Band)
    if action == "CALL":
        return percent_b <= 0.0 or touch in {"LOWER", "LOWER_0", "LOWER_BAND"}
    if action == "PUT":
        return percent_b >= 1.0 or touch in {"UPPER", "UPPER_1", "UPPER_BAND"}
    return False
