"""Grid risk filter for Believe."""

from typing import Dict

from .field_utils import boolean


def evaluate(fields: Dict[str, str], action: str) -> bool:
    """Return False when the payload explicitly blocks the grid."""
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    return not boolean(fields, "believe_risk_grid_block")
