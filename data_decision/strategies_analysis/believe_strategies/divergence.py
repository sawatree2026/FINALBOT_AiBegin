"""Divergence confirmation for Believe."""

from typing import Dict

from .field_utils import text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    value = text(fields, "m5_pa_divergence_alert", "pa_divergence_alert", "divergence_alert")
    return value in {"", "NONE", "FALSE"} or (
        "BULLISH" in value and action == "CALL"
    ) or ("BEARISH" in value and action == "PUT")
