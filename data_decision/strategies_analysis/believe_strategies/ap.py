"""AP confirmation for Believe."""

from typing import Dict

from .field_utils import aligned, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    signal = text(fields, "ap_signal")
    return signal in {"AP_NEUTRAL", "NEUTRAL"} or aligned(signal, action)
