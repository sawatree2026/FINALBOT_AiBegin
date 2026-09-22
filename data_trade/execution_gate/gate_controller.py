"""
Gate Controller — The Ultimate Decider for Part 3
=================================================
Guards final execution with the configured confidence threshold and Gemini/Chronos agreement.
"""

import logging
import re
from typing import Dict, Any, Optional, List
from data_trade.payload_sanitizer import sanitize_payload, sanitize_payload_text

logger = logging.getLogger("ExecutionGate")


class ExecutionGate:
    """The single execution authority for the Part 4 regime-gated policy."""

    POLICY_VERSION = "part4-regime-gated-trend-v1"
    MIN_ADX = 20.0
    MIN_DATA_QUALITY = 50.0

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.min_confidence = float(
            self.config.get("ai_mode", {}).get(
                "min_confidence",
                self.config.get("ml_mode", {}).get("min_confidence", 55.0),
            )
        )
        self.min_confidence = max(0.0, min(100.0, self.min_confidence))

    def evaluate_decision(
        self,
        symbol: str,
        ai_decision: Dict[str, Any],
        payload: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Final gate policy:
        - action must be CALL or PUT
        - confidence must meet configured threshold
        - Gemini/Chronos agreement must hold when provided
        - otherwise: rejected and action forced to WAIT
        """
        if not isinstance(ai_decision, dict):
            raise TypeError(f"FAIL-FAST: ai_decision must be a dict, got {type(ai_decision)}")

        action = str(ai_decision.get("action", "WAIT")).upper().strip()
        raw_expiry = ai_decision.get("expiry_minutes", ai_decision.get("expiry", 5))
        try:
            expiry_minutes = int(raw_expiry)
        except (TypeError, ValueError):
            expiry_minutes = -1
        confidence_score = float(ai_decision.get("confidence_score", 0.0))
        reason_th = str(
            ai_decision.get("ai_final_reason_th") or ai_decision.get("reason_th") or ""
        ).strip()
        engine_used = str(ai_decision.get("engine_used", "AI_ENGINE"))
        agreement_valid = bool(ai_decision.get("agreement_valid", True))
        evidence = self._extract_evidence(payload, ai_decision)
        rejection_reasons: List[str] = []

        if action == "WAIT":
            rejection_reasons.append("No trade signal")
        elif action not in ("CALL", "PUT"):
            rejection_reasons.append(f"Invalid signal ({action})")
        if expiry_minutes != 5:
            rejection_reasons.append(f"Expiry must be 5 minutes (received {raw_expiry!r})")
        if action in ("CALL", "PUT"):
            if confidence_score < self.min_confidence:
                rejection_reasons.append(
                    f"Confidence below threshold ({confidence_score:.1f}% < {self.min_confidence:.0f}%)"
                )
            if not agreement_valid:
                rejection_reasons.append("Gemini/Chronos disagreement")
            if evidence["m15_direction"] is None:
                rejection_reasons.append("Missing M15 primary direction")
            if evidence["m5_direction"] is None:
                rejection_reasons.append("Missing M5 confirmation direction")
            if evidence["regime"] is None:
                rejection_reasons.append("Missing M5 regime evidence")
            if evidence["adx"] is None:
                rejection_reasons.append("Missing M5 ADX evidence")
            elif evidence["adx"] < self.MIN_ADX:
                rejection_reasons.append(f"Low ADX ({evidence['adx']:.2f} < {self.MIN_ADX:.0f})")
            if evidence["risk"] is None:
                rejection_reasons.append("Missing risk evidence")
            elif evidence["risk"] in {"HIGH", "CRITICAL", "EXTREME"}:
                rejection_reasons.append(f"High risk ({evidence['risk']})")
            if evidence["quality_bad"]:
                rejection_reasons.append("Stale or low-quality market data")
            if evidence["regime"] == "CHOPPY":
                rejection_reasons.append("CHOPPY regime")
            if evidence["m15_direction"] and evidence["m5_direction"]:
                if evidence["m15_direction"] != evidence["m5_direction"]:
                    rejection_reasons.append("M15/M5 direction conflict")
                elif action != ("CALL" if evidence["m15_direction"] == "UP" else "PUT"):
                    rejection_reasons.append("Counter-trend action is disabled")

        approved = action in ("CALL", "PUT") and not rejection_reasons
        if approved:
            approved_reason = reason_th or (
                f"Approved {action}: M15 {evidence['m15_direction']} + "
                f"M5 {evidence['m5_direction']} trend confirmation"
            )
            rejection_reasons = []
        else:
            approved_reason = "; ".join(rejection_reasons) + " — WAIT"

        logger.info(
            f"[ExecutionGate] {symbol} => {'APPROVED' if approved else 'NOT APPROVED'}: "
            f"{action} -> {approved_reason}"
        )
        return {
            "approved": approved,
            "action": action if approved else "WAIT",
            "expiry_minutes": expiry_minutes,
            "confidence_score": confidence_score,
            "reason": approved_reason,
            "engine_used": engine_used,
            "agreement_valid": agreement_valid,
            "policy_version": self.POLICY_VERSION,
            "rejection_reasons": rejection_reasons,
            "m15_direction": evidence["m15_direction"],
            "m5_direction": evidence["m5_direction"],
            "m5_regime": evidence["regime"],
            "m5_adx": evidence["adx"],
            "risk_level": evidence["risk"],
            "data_quality_ok": not evidence["quality_bad"],
        }

    @staticmethod
    def _normalise_direction(value: Any) -> Optional[str]:
        text = str(value or "").upper().strip()
        if text in {"UP", "UPTREND", "BULLISH", "CALL", "BUY", "LONG"}:
            return "UP"
        if text in {"DOWN", "DOWNTREND", "BEARISH", "PUT", "SELL", "SHORT"}:
            return "DOWN"
        return None

    @classmethod
    def _extract_evidence(cls, payload: Any, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Read the actual Part 2 YAML-like payload without adding a dependency."""
        values: Dict[str, Any] = {}
        if isinstance(payload, dict):
            cleaned_payload, _ = sanitize_payload(payload, source="execution-gate")
            values.update(cleaned_payload)
        elif isinstance(payload, str):
            payload, _ = sanitize_payload_text(payload, source="execution-gate")
            for line in payload.splitlines():
                match = re.match(r"^\s*([A-Za-z0-9_]+):\s*[\"']?([^\"']*?)[\"']?\s*$", line)
                if match:
                    values[match.group(1).lower()] = match.group(2).strip()
        values.update({k.lower(): v for k, v in decision.items() if k not in values})

        def find(*keys: str) -> Any:
            for key in keys:
                if key.lower() in values and values[key.lower()] not in ("", None):
                    return values[key.lower()]
            return None

        m15 = cls._normalise_direction(find("m15_bias", "m15_direction", "primary_direction"))
        m5 = cls._normalise_direction(find("m5_bias", "m5_trend_direction", "m5_direction"))
        regime = str(find("m5_trend_type", "m5_regime", "regime") or "").upper().strip() or None
        adx_raw = find("m5_adx", "adx")
        try:
            adx = float(adx_raw) if adx_raw is not None else None
        except (TypeError, ValueError):
            adx = None
        risk = str(find("risk_level", "risk") or "").upper().strip() or None
        qualities = [find("m1_quality"), find("m5_quality"), find("data_quality")]
        quality_bad = any(
            str(q).upper() in {"STALE", "LOW", "POOR", "INVALID", "BAD"} for q in qualities if q is not None
        )
        quality_score = find("quality_score")
        if quality_score is not None:
            try:
                quality_bad = quality_bad or float(quality_score) < cls.MIN_DATA_QUALITY
            except (TypeError, ValueError):
                quality_bad = True
        return {
            "m15_direction": m15,
            "m5_direction": m5,
            "regime": regime,
            "adx": adx,
            "risk": risk,
            "quality_bad": quality_bad,
        }
