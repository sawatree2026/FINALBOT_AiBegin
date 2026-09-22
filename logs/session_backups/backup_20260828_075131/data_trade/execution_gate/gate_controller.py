"""
Gate Controller — The Ultimate Decider for Part 3
=================================================
กฎเดียวเท่านั้น: ถ้าคะแนน AI มากกว่าหรือเท่ากับ 70 คือ เทรดเลย!
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("ExecutionGate")


class ExecutionGate:
    """The Single Decisive Authority in Part 3."""

    MIN_CONFIDENCE: float = 70.0

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        pass

    def evaluate_decision(
        self,
        symbol: str,
        ai_decision: Dict[str, Any],
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        กฎชี้ขาดหนึ่งเดียว:
        - confidence_score >= 70 และ action CALL/PUT → APPROVED → ยิงออเดอร์
        - confidence_score < 70 หรือ action WAIT   → REJECTED → งด
        """
        if not isinstance(ai_decision, dict):
            raise TypeError(f"FAIL-FAST: ai_decision must be a dict, got {type(ai_decision)}")

        action = str(ai_decision.get("action", "WAIT")).upper().strip()
        expiry_minutes = int(ai_decision.get("expiry_minutes", 1))
        confidence_score = float(ai_decision.get("confidence_score", 0.0))
        reason_th = str(
            ai_decision.get("ai_final_reason_th") or ai_decision.get("reason_th") or ""
        ).strip()
        engine_used = str(ai_decision.get("engine_used", "AI_ENGINE"))

        # ── กฎที่ 1: CALL/PUT + confidence >= 70 → APPROVED ─────────────────
        if action in ("CALL", "PUT") and confidence_score >= self.MIN_CONFIDENCE:
            approved_reason = (
                reason_th or
                f"อนุมัติเข้าเทรด {action} (คะแนนความมั่นใจ {confidence_score:.1f}% >= {self.MIN_CONFIDENCE:.0f}%)"
            )
            logger.info(
                f"[ExecutionGate] {symbol} => APPROVED: {action} "
                f"({expiry_minutes}m, คะแนน {confidence_score:.1f}%) -> {approved_reason}"
            )
            return {
                "approved": True,
                "action": action,
                "expiry_minutes": expiry_minutes,
                "confidence_score": confidence_score,
                "reason": approved_reason,
                "engine_used": engine_used
            }

        # ── กฎที่ 2: งดเทรด ──────────────────────────────────────────────────
        if action in ("CALL", "PUT") and confidence_score < self.MIN_CONFIDENCE:
            reject_reason = (
                f"คะแนนความมั่นใจต่ำกว่าเกณฑ์ "
                f"({confidence_score:.1f}% < {self.MIN_CONFIDENCE:.0f}%) — งด"
            )
        elif action == "WAIT":
            reject_reason = "รอสัญญาณ AI (WAIT)"
        else:
            reject_reason = f"สัญญาณไม่ถูกต้อง ({action})"

        logger.info(
            f"[ExecutionGate] {symbol} => NOT APPROVED: {action} "
            f"(คะแนน {confidence_score:.1f}%) -> {reject_reason}"
        )
        return {
            "approved": False,
            "action": "WAIT" if action == "WAIT" else action,
            "expiry_minutes": expiry_minutes,
            "confidence_score": confidence_score,
            "reason": reject_reason,
            "engine_used": engine_used
        }

