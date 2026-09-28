"""Field utilities for NS Strategy Mode."""
from typing import Dict

def _value(fields: Dict[str, str], key: str) -> str:
    if key not in fields:
        raise ValueError(f"Required NS payload field missing: {key}")
    val = str(fields[key]).strip()
    if not val:
        raise ValueError(f"Required NS payload field is empty: {key}")
    return val

def text(fields: Dict[str, str], key: str) -> str:
    return _value(fields, key).upper()

def number(fields: Dict[str, str], key: str) -> float:
    try:
        return float(_value(fields, key).replace("%", ""))
    except ValueError as exc:
        raise ValueError(f"Invalid numeric NS payload field: {key}") from exc

def boolean(fields: Dict[str, str], key: str) -> bool:
    val = text(fields, key)
    if val in {"TRUE", "1", "YES", "PASS", "PASSED"}:
        return True
    if val in {"FALSE", "0", "NO", "FAIL", "FAILED"}:
        return False
    raise ValueError(f"Invalid boolean NS payload field: {key}")
