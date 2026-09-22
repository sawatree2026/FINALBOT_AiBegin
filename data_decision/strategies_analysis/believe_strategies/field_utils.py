"""Strict helpers for disk-backed Believe field evaluation."""

from typing import Dict


def _value(fields: Dict[str, str], key: str) -> str:
    if key not in fields:
        raise ValueError(f"Required Believe payload field missing: {key}")
    value = str(fields[key]).strip()
    if not value:
        raise ValueError(f"Required Believe payload field is empty: {key}")
    return value


def text(fields: Dict[str, str], key: str) -> str:
    return _value(fields, key).upper()


def number(fields: Dict[str, str], key: str) -> float:
    try:
        return float(_value(fields, key).replace("%", ""))
    except ValueError as exc:
        if str(exc).startswith("Required Believe payload field"):
            raise
        raise ValueError(f"Invalid numeric Believe payload field: {key}") from exc


def boolean(fields: Dict[str, str], key: str) -> bool:
    value = text(fields, key)
    if value in {"TRUE", "1", "YES", "Y", "PASS", "PASSED"}:
        return True
    if value in {"FALSE", "0", "NO", "N", "FAIL", "FAILED"}:
        return False
    raise ValueError(f"Invalid boolean Believe payload field: {key}")


def aligned(signal: str, action: str) -> bool:
    return (
        action == "CALL" and signal in {"BULLISH", "UP", "CALL", "BUY", "LONG"}
    ) or (
        action == "PUT" and signal in {"BEARISH", "DOWN", "PUT", "SELL", "SHORT"}
    )
