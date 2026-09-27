from typing import Dict
from .field_utils import boolean, number, text

def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    percent_b = number(fields, "believe_bb_percent_b")
    touch = text(fields, "believe_bb_touch").upper()
    if action == "CALL":
        has_touch_low = boolean(fields, "believe_bb_touch_low") if "believe_bb_touch_low" in fields else False
        return percent_b <= 0.0 or "LOWER" in touch or touch == "0" or has_touch_low
    if action == "PUT":
        has_touch_high = boolean(fields, "believe_bb_touch_high") if "believe_bb_touch_high" in fields else False
        return percent_b >= 1.0 or "UPPER" in touch or touch == "1" or has_touch_high
    return False
