"""Support and resistance confirmation for Believe."""

from typing import Dict

from .field_utils import text


_BLOCKING_INTERACTIONS = {
    "BLOCK",
    "BLOCKED",
    "RESISTANCE_BLOCK",
    "SUPPORT_BLOCK",
    "GRID_BLOCK",
}


def evaluate(fields: Dict[str, str], action: str) -> bool:
    """Return False when support/resistance interaction blocks the action."""
    del action
    interaction = text(fields, "m5_pa_sr_interaction")
    return interaction not in _BLOCKING_INTERACTIONS
