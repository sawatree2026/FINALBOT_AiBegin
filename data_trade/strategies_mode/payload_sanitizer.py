"""Sanitize legacy Part 2 decision fields before active model/gate dispatch."""

from copy import deepcopy
import json
import logging
import re
from typing import Any, Dict, Tuple

logger = logging.getLogger("PayloadSanitizer")

LEGACY_DECISION_FIELDS = frozenset({
    "dl_tradeable",
    "dl_stability_score",
    "dl_quality_score",
    "dl_risk_level",
    "ai_confidence_score",
    "ai_suggested_expiry_minutes",
    "ai_suggested_action",
})


def sanitize_payload(payload: Any, *, source: str = "in-memory") -> Tuple[Any, bool]:
    """Return a non-mutating payload with the legacy decision layer removed."""
    if isinstance(payload, dict):
        cleaned = deepcopy(payload)
        stripped = "decision_layer" in cleaned
        cleaned.pop("decision_layer", None)
        for key in list(cleaned):
            if str(key).lower() in LEGACY_DECISION_FIELDS:
                del cleaned[key]
                stripped = True
        if stripped:
            logger.warning(
                "[PayloadSanitizer] LEGACY_DECISION_LAYER_STRIPPED "
                "reason_code=LEGACY_DECISION_FIELDS source=%s",
                source,
            )
        return cleaned, stripped
    if isinstance(payload, str):
        return sanitize_payload_text(payload, source=source)
    if payload is None:
        return payload, False
    raise TypeError(f"FAIL-FAST: Unsupported payload type: {type(payload)}")


def sanitize_payload_text(payload_text: str, *, source: str = "payload-text") -> Tuple[str, bool]:
    """Remove the YAML-like decision_layer block without changing the source file."""
    if not isinstance(payload_text, str):
        raise TypeError("FAIL-FAST: payload_text must be a string")

    lines = payload_text.splitlines()
    output = []
    stripped = False
    skipping_layer = False
    layer_indent = 0
    for line in lines:
        match = re.match(r"^(\s*)decision_layer\s*:\s*(?:#.*)?$", line, re.IGNORECASE)
        if match:
            stripped = True
            skipping_layer = True
            layer_indent = len(match.group(1).expandtabs(4))
            continue
        if skipping_layer:
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" \t"))
            if indent > layer_indent:
                stripped = True
                continue
            skipping_layer = False
        if re.match(
            r"^\s*(?:dl_tradeable|dl_stability_score|dl_quality_score|dl_risk_level|"
            r"ai_confidence_score|ai_suggested_expiry_minutes|ai_suggested_action)\s*:",
            line,
            re.IGNORECASE,
        ):
            stripped = True
            continue
        output.append(line)

    cleaned = "\n".join(output)
    if payload_text.endswith(("\n", "\r")):
        cleaned += "\n"
    if stripped:
        logger.warning(
            "[PayloadSanitizer] LEGACY_DECISION_LAYER_STRIPPED "
            "reason_code=LEGACY_DECISION_FIELDS source=%s",
            source,
        )
    return cleaned, stripped


def payload_to_text(payload: Any, *, source: str = "in-memory") -> Tuple[str, bool]:
    """Sanitize and serialize an in-memory payload for model transport."""
    cleaned, stripped = sanitize_payload(payload, source=source)
    if isinstance(cleaned, str):
        return cleaned, stripped
    if isinstance(cleaned, dict):
        return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")), stripped
    raise TypeError(f"FAIL-FAST: Unsupported payload type: {type(payload)}")
