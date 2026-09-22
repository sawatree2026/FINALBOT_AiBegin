"""Small, conservative helpers for disk-backed Believe field evaluation."""

from typing import Any, Dict, Optional


def text(fields: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(fields.get(key, "") or "").strip()
        if value:
            return value.upper()
    return ""


def number(fields: Dict[str, str], *keys: str) -> Optional[float]:
    for key in keys:
        try:
            return float(str(fields.get(key, "")).strip().replace("%", ""))
        except (TypeError, ValueError):
            continue
    return None


def boolean(fields: Dict[str, str], *keys: str) -> Optional[bool]:
    value = text(fields, *keys)
    if value in {"TRUE", "1", "YES", "Y", "PASS", "PASSED"}:
        return True
    if value in {"FALSE", "0", "NO", "N", "FAIL", "FAILED"}:
        return False
    return None


def aligned(signal: str, action: str) -> bool:
    return (
        action == "CALL" and signal in {"BULLISH", "UP", "CALL", "BUY", "LONG"}
    ) or (
        action == "PUT" and signal in {"BEARISH", "DOWN", "PUT", "SELL", "SHORT"}
    )
