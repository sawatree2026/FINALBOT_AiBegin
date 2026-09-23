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

    # Touch is a semantic interpretation of %B, never an independent signal.
    # Keep the canonical thresholds aligned with the live strategies evaluator.
    touch = text(fields, "believe_bb_touch")
    expected_touch = (
        "LOWER" if percent_b <= 0.15
        else "UPPER" if percent_b >= 0.85
        else "NONE"
    )
    accepted_touch = {
        "LOWER": {"LOWER", "LOWER_0", "LOWER_BAND"},
        "UPPER": {"UPPER", "UPPER_1", "UPPER_BAND"},
        "NONE": {"NONE"},
    }
    if touch not in accepted_touch[expected_touch]:
        raise ValueError(
            "Inconsistent Believe Bollinger touch: touch must be derived from %B"
        )
    if action == "CALL":
        return percent_b <= 0.15
    if action == "PUT":
        return percent_b >= 0.85
    return False
