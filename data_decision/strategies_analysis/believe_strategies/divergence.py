"""Divergence confirmation for Believe."""

from typing import Dict

from .field_utils import text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    value = text(fields, "m1_divergence_type")
    peak_count = int(float(fields.get("m1_divergence_peak_count", "0")))
    return peak_count in {2, 3} and (
        ("BULLISH" in value and action == "CALL")
        or ("BEARISH" in value and action == "PUT")
    )
