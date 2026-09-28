"""Gray Candle Filter module for NS Strategy (Nemesis V.2 3.3)."""
from typing import Dict

def is_clear(fields: Dict[str, str]) -> bool:
    # Rule 3.3: Must have zero gray candle in 15m window
    gray_present = fields.get("gray_candle_present", fields.get("m15_gray_candle_present", "FALSE")).upper() in {"TRUE", "1", "YES"}
    doji_present = fields.get("doji_present", fields.get("m15_doji_present", "FALSE")).upper() in {"TRUE", "1", "YES"}
    return not (gray_present or doji_present)
