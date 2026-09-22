"""Support, resistance, and Grid risk filter for Believe."""

from typing import Dict

from .field_utils import boolean, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    blocked = boolean(fields, "believe_risk_grid_block", "m5_pa_grid_block")
    interaction = text(fields, "m5_pa_sr_interaction", "pa_sr_interaction")
    return blocked is not True and interaction not in {
        "BLOCK", "BLOCKED", "RESISTANCE_BLOCK", "SUPPORT_BLOCK", "GRID_BLOCK"
    }
