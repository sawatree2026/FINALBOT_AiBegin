"""AP confirmation for Believe."""

from typing import Dict

from .field_utils import aligned, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    signal = text(fields, "ap_signal", "ap")
    return signal in {"", "AP_NEUTRAL", "NEUTRAL"} or aligned(signal, action)
