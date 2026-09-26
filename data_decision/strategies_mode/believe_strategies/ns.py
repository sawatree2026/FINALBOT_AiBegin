"""NS confirmation for Believe."""

from typing import Dict

from .field_utils import aligned, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    signal = text(fields, "ns_signal")
    return signal in {"NS_NEUTRAL", "NEUTRAL"} or aligned(signal, action)
