"""
Executor Manager — Master Controller for Part 3 (Data Trade & Execution)
==========================================================================
หน้าที่: ผู้บัญชาการเทรดเท่านั้น (Trade & Risk Commander)

Flow:
1. รับสะกิดจาก Orchestrator Part 2 ผ่าน on_orchestrator_payload_saved()
2. รวบรวม pending symbols ใน thread-safe queue
3. flush → ส่ง 99 payload ให้ Gemini และ Chronos-2 ONNX
4. ยิงได้เมื่อ Gemini >= 55% และ Gemini เห็นตรงกับ Chronos

Concurrency: รองรับ 1 ถึง 10+ คู่เงินพร้อมกันโดยไม่รอคิว
"""

import os
import time
import json
import logging
import traceback
import threading
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

from config_setting.config_loader import load_settings
from data_decision.ai_analysis.artificial_intelligence.ai_dispatcher import SystemPrompt
from data_trade.execution_gate.gate_controller import ExecutionGate
from data_trade.execution_gate.money_manager import MoneyManager
from data_trade.execution_gate.broker_executor import BrokerExecutor
from data_trade.execution_gate.order_tracker import OrderTracker
from data_trade.payload_sanitizer import payload_to_text, sanitize_payload, sanitize_payload_text

logger = logging.getLogger("ExecutorManager")


class ExecutorManager:
    """Central entry point for Part 3 trade decision and execution pipeline."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.settings = config or load_settings(reload=False)
        self.execution_gate = ExecutionGate(config=self.settings)
        self.money_manager = MoneyManager(config=self.settings)
        self.broker_executor = BrokerExecutor()
        self.order_tracker = OrderTracker(money_manager=self.money_manager)
        self.audit_csv_path = os.path.join("data_base", "output_trade", "decision_gate_audit.csv")
        from data_trade.execution_gate.chronos_dispatcher import ChronosDispatcher
        self.chronos_dispatcher = ChronosDispatcher.get_instance(self.settings)
        self.min_gemini_confidence = float(
            self.settings.get("ai_mode", {}).get("min_confidence", 55)
        )

        # ── Live Execution Flag ─────────────────────────────────────────────
        self.enable_live_execution: bool = bool(
            self.settings.get("data_trade", {}).get("enable_live_execution", True)
        )

        # ── Concurrent Dispatch State (thread-safe) ─────────────────────────
        self._pending_lock = threading.Lock()
        self._pending_tasks: Dict[str, Dict[str, Any]] = {}   # legacy in-process queue; disk polling is authoritative
        self._flush_lock = threading.Lock()         # ป้องกัน concurrent flush ซ้อน
        self._broker_adapter: Optional[Any] = None  # เก็บ broker adapter ล่าสุด
        self._is_warmup_round: bool = False         # BOSS ORDER: Disabled warmup round
        self._processed_decision_files: set[str] = set()

        logger.info(
            f"[ExecutorManager] Initialized | LiveExecution: {self.enable_live_execution} | "
            f"N-Symbol Concurrent Dispatch: ENABLED | Gemini/Chronos agreement | Confidence Gate: >= 55% | "
            f"Warmup Round: DISABLED (เทรดตั้งแต่รอบแรก)"
        )

    def process_decision_files(self, symbols: List[str]) -> None:
        """Consume Part 3 decision JSON files from SSD and execute approved decisions."""
        active_mode = str(self.settings.get("active_mode", "ml_mode")).lower()
        decision_cfg = self.settings.get("data_decision", {})
        ai_root = decision_cfg.get(
            "ai_output_dir", os.path.join("data_base", "output_decision", "ai_decision")
        )
        strategy_root = decision_cfg.get(
            "strategies_output_dir",
            os.path.join("data_base", "output_decision", "strategies_decision"),
        )
        for symbol in symbols:
            ai_path = self._latest_decision_file(ai_root, symbol)
            strategy_path = self._latest_decision_file(strategy_root, symbol)
            selected_path = strategy_path if active_mode == "strategies_mode" else ai_path
            if not selected_path:
                continue
            decision_key = f"{active_mode}:{selected_path}:{os.path.getmtime(selected_path)}"
            if decision_key in self._processed_decision_files:
                continue

            with open(selected_path, "r", encoding="utf-8") as handle:
                selected_decision = json.load(handle)
            action = str(selected_decision.get("action", "WAIT")).upper()
            agreement = action in {"CALL", "PUT"} if active_mode == "strategies_mode" else True
            payload_path = selected_decision.get("payload_filepath")
            if not payload_path or not os.path.isfile(payload_path):
                raise FileNotFoundError(f"FAIL-FAST: Decision source payload missing for {symbol}: {payload_path}")
            with open(payload_path, "r", encoding="utf-8") as handle:
                payload_text = handle.read()

            merged = {
                **selected_decision,
                "action": action if agreement else "WAIT",
                "agreement_valid": agreement,
                "payload_text": payload_text,
                "payload_filepath": payload_path,
            }
            self._execute_single_decision(symbol=symbol, ai_decision=merged, broker_adapter=self._broker_adapter)
            self._processed_decision_files.add(decision_key)

    @staticmethod
    def _latest_decision_file(root: str, symbol: str) -> Optional[str]:
        symbol_dir = os.path.join(root, symbol)
        if not os.path.isdir(symbol_dir):
            return None
        files = [
            os.path.join(symbol_dir, name)
            for name in os.listdir(symbol_dir)
            if name.endswith(".json") and os.path.isfile(os.path.join(symbol_dir, name))
        ]
        return max(files, key=os.path.getmtime) if files else None


    def on_orchestrator_payload_saved(
        self,
        prompt_filepath_or_batch: Any,
        symbol: Optional[str] = None,
        broker_adapter: Optional[Any] = None
    ) -> None:
        """
        Event Handler: เรียกเมื่อ Orchestrator Part 2 บันทึก payload เสร็จ.
        รองรับทั้งแบบ Batch (List[Tuple[str, str]]) และแบบเดี่ยว (filepath, symbol).
        """
        if broker_adapter is not None:
            self._broker_adapter = broker_adapter

        # ── Case A: Unified Batch (List of (symbol, filepath)) ───────────────
        if isinstance(prompt_filepath_or_batch, list):
            if not prompt_filepath_or_batch:
                return

            with self._pending_lock:
                for item in prompt_filepath_or_batch:
                    if isinstance(item, (tuple, list)) and len(item) in (2, 3):
                        sym, fp = item[0], item[1]
                        payload = item[2] if len(item) == 3 else None
                        if sym and (fp or payload):
                            self._pending_tasks[sym] = {
                                "filepath": fp,
                                "payload_text": self._payload_to_text(payload),
                                "payload": self._sanitize_payload_dict(payload),
                            }
                    elif isinstance(item, dict):
                        sym = item.get("symbol")
                        fp = item.get("filepath") or item.get("prompt_filepath")
                        payload_text = item.get("payload_text")
                        payload = item.get("payload")
                        if payload_text is None:
                            payload_text = payload
                        if sym and (fp or payload_text):
                            self._pending_tasks[sym] = {
                                "filepath": fp,
                                "payload_text": self._payload_to_text(payload_text),
                                "payload": self._sanitize_payload_dict(payload),
                            }
                queue_size = len(self._pending_tasks)

            logger.info(
                f"[ExecutorManager] Queued batch of {len(prompt_filepath_or_batch)} symbol(s) "
                f"(pending queue: {queue_size} symbol(s))"
            )

            flush_thread = threading.Thread(
                target=self._flush_pending,
                kwargs={"triggering_symbol": "BATCH"},
                daemon=True,
                name="FlushThread-BATCH"
            )
            flush_thread.start()
            return

        # ── Case B: Single Item (filepath, symbol) ───────────────────────────
        if isinstance(prompt_filepath_or_batch, dict):
            payload = prompt_filepath_or_batch.get("payload")
            prompt_filepath = (
                prompt_filepath_or_batch.get("filepath")
                or prompt_filepath_or_batch.get("prompt_filepath")
            )
            payload_text = prompt_filepath_or_batch.get("payload_text")
            if payload_text is None:
                payload_text = payload
        else:
            prompt_filepath = prompt_filepath_or_batch
            payload_text = None
        if not symbol or not isinstance(symbol, str):
            logger.error(f"[ExecutorManager] Invalid symbol in nudge: {symbol!r}")
            return
        if not prompt_filepath and not payload_text:
            logger.error(f"[ExecutorManager] Missing filepath and in-memory payload for {symbol}")
            return

        with self._pending_lock:
            self._pending_tasks[symbol] = {
                "filepath": prompt_filepath,
                "payload_text": self._payload_to_text(payload_text),
                "payload": self._sanitize_payload_dict(payload_text),
            }
            queue_size = len(self._pending_tasks)

        logger.info(
            f"[ExecutorManager] Queued '{symbol}' "
            f"(pending queue: {queue_size} symbol(s))"
        )

        flush_thread = threading.Thread(
            target=self._flush_pending,
            kwargs={"triggering_symbol": symbol},
            daemon=True,
            name=f"FlushThread-{symbol}"
        )
        flush_thread.start()

    def _append_joint_decision_audit(
        self,
        symbol: str,
        payload_id: str,
        prompt_filepath: str,
        gemini_decision: Dict[str, Any],
        chronos_decision: Dict[str, Any],
        merged_decision: Dict[str, Any],
    ) -> None:
        """Write one audit row combining Gemini, Chronos, agreement, gate and broker actions."""
        try:
            os.makedirs(os.path.dirname(self.audit_csv_path), exist_ok=True)
            row = {
                "timestamp": datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "payload_id": payload_id,
                "prompt_filepath": prompt_filepath,
                "gemini_action": str(gemini_decision.get("action", "WAIT")).upper(),
                "gemini_confidence": float(gemini_decision.get("confidence_score", 0.0) or 0.0),
                "chronos_action": str(chronos_decision.get("action", "WAIT")).upper(),
                "chronos_confidence": float(chronos_decision.get("confidence", chronos_decision.get("confidence_score", 0.0)) or 0.0),
                "agreement_valid": bool(merged_decision.get("agreement_valid", False)),
                "gate_approved": bool(merged_decision.get("gate_approved", False)),
                "final_action": str(merged_decision.get("action", "WAIT")).upper(),
                "final_confidence": float(merged_decision.get("confidence_score", 0.0) or 0.0),
                "reason": str(merged_decision.get("reason_th") or merged_decision.get("reason") or "").strip(),
                "policy_version": merged_decision.get("policy_version", ""),
                "rejection_reasons": " | ".join(merged_decision.get("rejection_reasons", [])),
                "m15_direction": merged_decision.get("m15_direction", ""),
                "m5_direction": merged_decision.get("m5_direction", ""),
                "m5_regime": merged_decision.get("m5_regime", ""),
                "m5_adx": merged_decision.get("m5_adx", ""),
                "risk_level": merged_decision.get("risk_level", ""),
                "data_quality_ok": merged_decision.get("data_quality_ok", ""),
                "broker_result": merged_decision.get("broker_result", "PENDING"),
            }
            fieldnames = [
                "timestamp", "symbol", "payload_id", "prompt_filepath",
                "gemini_action", "gemini_confidence",
                "chronos_action", "chronos_confidence",
                "agreement_valid", "gate_approved",
                "final_action", "final_confidence", "reason",
                "policy_version", "rejection_reasons", "m15_direction",
                "m5_direction", "m5_regime", "m5_adx", "risk_level",
                "data_quality_ok", "broker_result",
            ]
            file_exists = os.path.isfile(self.audit_csv_path) and os.path.getsize(self.audit_csv_path) > 0
            with open(self.audit_csv_path, "a", newline="", encoding="utf-8") as f:
                import csv
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as exc:
            logger.warning(f"[ExecutorManager] Could not append decision audit record for {symbol}: {exc}")

    def _flush_pending(self, triggering_symbol: str = "") -> None:
        """
        ดึง pending tasks ทั้งหมดออกจาก queue แล้วยิง concurrent dispatch ทีเดียว.
        ✅ FIX: ใช้ blocking lock with timeout แทน non-blocking skip เพื่อป้องกัน signal ตกหล่น
        หลัง flush เสร็จจะเช็ค pending tasks อีกครั้ง ถ้ามีก็ flush ต่อ
        """
        # รอจนกว่าจะได้ flush lock (timeout 5 วินาที)
        if not self._flush_lock.acquire(blocking=True, timeout=5.0):
            logger.warning(
                f"[ExecutorManager] Flush lock timeout (triggered by {triggering_symbol}), "
                f"signal queued for next flush cycle."
            )
            return

        try:
            with self._pending_lock:
                if not self._pending_tasks:
                    return
                tasks = [
                    (symbol, task.get("filepath"), task.get("payload_text"), task.get("payload"))
                    for symbol, task in self._pending_tasks.items()
                ]
                self._pending_tasks.clear()

            logger.info(
                f"[ExecutorManager] Concurrent flush: {len(tasks)} symbol(s) → "
                f"{[t[0] for t in tasks]}"
            )

            # ── AI / ML Decision Dispatch ───────────────────────────────────
            try:
                decisions = self._dispatch_dual_decisions(tasks)
            except Exception as e:
                logger.exception(
                    f"[ExecutorManager] decision dispatch crashed: {e}"
                )
                traceback.print_exc()
                self._halt_process(
                    f"FAIL-FAST: Decision dispatch failed; trading halted: {e}"
                )

            # ── Process each decision: ExecutionGate → BrokerExecutor ────────

            for symbol, ai_decision in decisions.items():
                try:
                    self._execute_single_decision(
                        symbol=symbol,
                        ai_decision=ai_decision,
                        broker_adapter=self._broker_adapter
                    )
                except Exception as e:
                    logger.exception(
                        f"[ExecutorManager] _execute_single_decision failed for {symbol}: {e}"
                    )
                    traceback.print_exc()
                    self._halt_process(
                        f"FAIL-FAST: Execution failed for {symbol}; trading halted: {e}"
                    )

        finally:
            self._flush_lock.release()
            
            # ✅ FIX: หลัง flush เสร็จ เช็ค pending tasks อีกครั้ง
            # ถ้ามี signal ใหม่เข้ามาระหว่าง flush ก็ flush ต่อเลย
            with self._pending_lock:
                has_pending = bool(self._pending_tasks)
            
            if has_pending:
                logger.info(
                    f"[ExecutorManager] New signals detected during flush, "
                    f"triggering follow-up flush cycle."
                )
                # สร้าง thread ใหม่เพื่อ flush ต่อ (recursive flush)
                follow_up_thread = threading.Thread(
                    target=self._flush_pending,
                    kwargs={"triggering_symbol": "follow-up"},
                    daemon=True,
                    name="FlushThread-follow-up"
                )
                follow_up_thread.start()

    def _dispatch_dual_decisions(
        self, tasks: List[Tuple[str, Optional[str], Optional[str], Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Run Gemini and Chronos on the same payload and require agreement."""
        dispatch_started = time.perf_counter()
        in_memory_count = sum(1 for _, _, payload_text, _ in tasks if payload_text is not None)
        dispatch_tasks = []
        for symbol, filepath, payload_text, payload in tasks:
            if payload_text is None:
                if not filepath:
                    raise ValueError(
                        f"FAIL-FAST: No filepath or in-memory payload for {symbol}"
                    )
                payload_text = self._read_payload_text(filepath)
            payload_text, _ = sanitize_payload_text(
                payload_text, source=filepath or f"in-memory:{symbol}"
            )
            dispatch_tasks.append((symbol, filepath, payload_text, payload))

        try:
            from data_decision.ai_analysis.artificial_intelligence.ai_dispatcher import SystemPrompt
            gemini = SystemPrompt.process_ai_decisions_concurrent([
                (symbol, filepath, payload_text)
                for symbol, filepath, payload_text, _ in dispatch_tasks
            ])
            chronos = {
                symbol: self.chronos_dispatcher.process_payload(
                    symbol,
                    payload_text=payload_text,
                    payload=payload,
                    prompt_filepath=filepath,
                )
                for symbol, filepath, payload_text, payload in dispatch_tasks
            }
        except Exception as e:
            raise RuntimeError(
                f"FAIL-FAST: Gemini/Chronos dispatch failed; trading halted: {e}"
            ) from e
        logger.info(
            "[ExecutorManager] Dual dispatch completed in %.1fms; payload transport=%s",
            (time.perf_counter() - dispatch_started) * 1000.0,
            f"in-memory ({in_memory_count}/{len(dispatch_tasks)})",
        )

        merged: Dict[str, Dict[str, Any]] = {}
        for symbol, filepath, payload_text, _ in dispatch_tasks:
            gemini_decision = gemini.get(symbol)
            chronos_decision = chronos.get(symbol)
            if not isinstance(gemini_decision, dict) or not isinstance(chronos_decision, dict):
                raise RuntimeError(f"FAIL-FAST: Missing Gemini or Chronos decision for {symbol}")

            gemini_action = str(gemini_decision.get("action", "WAIT")).upper()
            chronos_action = str(chronos_decision.get("action", "WAIT")).upper()
            gemini_confidence = float(gemini_decision.get("confidence_score", 0.0))
            chronos_confidence = float(
                chronos_decision.get("confidence_score", chronos_decision.get("confidence", 0.0))
            )
            agreement_valid = (
                gemini_action in ("CALL", "PUT")
                and chronos_action in ("CALL", "PUT")
                and gemini_action == chronos_action
                and gemini_confidence >= self.min_gemini_confidence
                and chronos_confidence >= self.min_gemini_confidence
            )
            approved_action = gemini_action if agreement_valid else "WAIT"
            merged[symbol] = {
                **gemini_decision,
                "payload_text": payload_text,
                "action": approved_action,
                "confidence_score": gemini_confidence,
                "engine_used": "GEMINI+CHRONOS_2_ONNX",
                "gemini_decision": gemini_decision,
                "chronos_decision": chronos_decision,
                "agreement_valid": agreement_valid,
                "gate_approved": agreement_valid,
                "reason_th": (
                    f"Gemini {gemini_action} {gemini_confidence:.0f}% + "
                    f"Chronos {chronos_action} {chronos_confidence:.0f}%: "
                    f"{'AGREEMENT' if agreement_valid else 'NO AGREEMENT'}"
                ),
            }
            policy_preview = self.execution_gate.evaluate_decision(
                symbol, merged[symbol], payload=merged[symbol]["payload_text"]
            )
            merged[symbol].update({
                key: policy_preview.get(key) for key in (
                    "policy_version", "rejection_reasons", "m15_direction", "m5_direction",
                    "m5_regime", "m5_adx", "risk_level", "data_quality_ok"
                )
            })
            self._append_joint_decision_audit(
                symbol=symbol,
                payload_id=str(gemini_decision.get("ID") or chronos_decision.get("ID") or symbol),
                prompt_filepath=filepath,
                gemini_decision=gemini_decision,
                chronos_decision=chronos_decision,
                merged_decision=merged[symbol],
            )
        return merged

    @staticmethod
    def _read_payload_text(filepath: str) -> str:
        """Load the immutable Part 2 payload for the execution gate."""
        with open(filepath, "r", encoding="utf-8") as handle:
            content = handle.read()
        cleaned, _ = sanitize_payload_text(content, source=filepath)
        return cleaned

    @staticmethod
    def _payload_to_text(payload: Any) -> Optional[str]:
        """Convert an optional in-memory payload to transport text without mutation."""
        if payload is None:
            return None
        text, _ = payload_to_text(payload, source="executor-queue")
        return text

    @staticmethod
    def _sanitize_payload_dict(payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        cleaned, _ = sanitize_payload(payload, source="executor-queue")
        return cleaned

    def _execute_single_decision(
        self,
        symbol: str,
        ai_decision: Dict[str, Any],
        broker_adapter: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        ประมวลผลการยิงออเดอร์ตามสัญญาณ AI / ML (Direct Execution)
        เงื่อนไข:
        1. ดึงยอดเงินจาก broker_adapter (ดึงไม่ได้ = หยุดทันที)
        2. ตรวจสอบ money_manager.can_trade(symbol=symbol, balance=balance)
        3. ถ้า not can_trade -> ส่งผล BLOCKED_BY_RISK ทันที
        4. ถ้า action in ("CALL", "PUT") -> ยิงออเดอร์ทันที (หาก enable_live_execution=True)
        5. เมื่อยิงสำเร็จ -> บันทึกเข้า order_tracker เพื่อติดตามและแจ้ง money_manager เมื่อจบสัญญา
        """
        if not isinstance(ai_decision, dict):
            raise TypeError(f"FAIL-FAST: ai_decision must be a dict, got {type(ai_decision)}")

        gate_result = self.execution_gate.evaluate_decision(
            symbol, ai_decision, payload=ai_decision.get("payload_text")
        )
        ai_decision = {
            **ai_decision,
            "agreement_valid": bool(gate_result.get("agreement_valid", True)),
            "gate_approved": bool(gate_result.get("approved", False)),
            "action": str(gate_result.get("action", "WAIT")).upper(),
            "confidence_score": float(gate_result.get("confidence_score", ai_decision.get("confidence_score", 0.0))),
            "reason_th": str(gate_result.get("reason") or ai_decision.get("reason_th") or "").strip(),
        }

        action = str(ai_decision.get("action", "WAIT")).upper().strip()
        expiry_minutes = int(ai_decision.get("expiry_minutes", 5))
        if expiry_minutes != 5:
            raise ValueError(
                f"FAIL-FAST: Invalid Binary Options expiry {expiry_minutes}; "
                "M5 strategy requires exactly 5 minutes"
            )
        confidence_score = float(ai_decision.get("confidence_score", 0.0))
        reason_th = str(
            ai_decision.get("ai_final_reason_th") or ai_decision.get("reason_th") or ""
        ).strip()
        engine_used = str(ai_decision.get("engine_used", "AI_ENGINE"))

        if not bool(gate_result.get("approved", False)):
            wait_reason = reason_th or gate_result.get("reason") or "WAIT due to execution gate rejection"
            logger.info(f"[ExecutorManager] {symbol} rejected by execution gate: {wait_reason}")
            return {
                "symbol": symbol,
                "action": "WAIT",
                "expiry_minutes": 5,
                "confidence_score": confidence_score,
                "reason": wait_reason,
                "should_execute": False,
                "order_executed": False,
                "order_data": None,
                "ai_decision": ai_decision,
                "gate_result": gate_result,
                "risk_status": self.money_manager.get_risk_status(),
            }

        # ── Step 1: ดึงยอดเงินคงเหลือจาก Broker ──────────────────────────────
        adapter_to_use = broker_adapter or self._broker_adapter
        if adapter_to_use is None:
            raise RuntimeError(
                f"FAIL-FAST: No broker adapter available for {symbol}; trading halted"
            )
        try:
            if hasattr(adapter_to_use, "get_balance"):
                balance = float(adapter_to_use.get_balance())
            elif hasattr(adapter_to_use, "api") and hasattr(adapter_to_use.api, "get_balance"):
                balance = float(adapter_to_use.api.get_balance())
            else:
                raise AttributeError("broker adapter has no get_balance method")
        except Exception as e:
            logger.exception(
                f"[ExecutorManager] Could not retrieve broker balance for {symbol}: {e}"
            )
            raise RuntimeError(
                f"FAIL-FAST: Broker balance unavailable for {symbol}; trading halted"
            ) from e

        # ── Step 2: ตรวจสอบ Risk Gate (ห้ามยิงซ้ำคู่เดิม / TP / SL / Balance) ────
        can_trade, risk_reason = self.money_manager.can_trade(symbol=symbol, balance=balance)
        if not can_trade:
            logger.info(f"[ExecutorManager] {symbol} blocked by risk gate: {risk_reason}")
            return {
                "symbol": symbol,
                "action": "BLOCKED_BY_RISK",
                "expiry_minutes": 5,
                "confidence_score": confidence_score,
                "reason": risk_reason,
                "should_execute": False,
                "order_executed": False,
                "order_data": None,
                "ai_decision": ai_decision,
                "risk_status": self.money_manager.get_risk_status()
            }

        # ── Step 3: กรณีไม่มีสัญญาณเทรด (WAIT) ───────────────────────────────
        if action not in ("CALL", "PUT"):
            wait_reason = reason_th or f"รอสัญญาณ AI / ML (Action={action})"
            logger.info(f"[ExecutorManager] {symbol} => {action}: {wait_reason}")
            return {
                "symbol": symbol,
                "action": action,
                "expiry_minutes": 5,
                "confidence_score": confidence_score,
                "reason": wait_reason,
                "should_execute": False,
                "order_executed": False,
                "order_data": None,
                "ai_decision": ai_decision,
                "risk_status": self.money_manager.get_risk_status()
            }

        # ── Step 4: ตรวจสอบ Live Execution Gate ──────────────────────────────
        should_execute_order = self.enable_live_execution
        if not self.enable_live_execution:
            logger.info(
                f"[ExecutorManager] [SIGNAL_ONLY] {symbol}: "
                f"Action={action} Confidence={confidence_score}% Expiry={expiry_minutes}m "
                f"(enable_live_execution=False)"
            )

        # ── Step 5: ยิงออเดอร์ผ่าน BrokerExecutor ────────────────────────────
        order_data = None
        if should_execute_order:
            stake = self.money_manager.get_stake(symbol)

            try:
                order_data = self.broker_executor.execute_order(
                    symbol=symbol,
                    action=action,
                    expiry_minutes=expiry_minutes,
                    stake=stake,
                    broker_adapter=adapter_to_use
                )
                logger.info(
                    f"[ExecutorManager] Broker order dispatched for {symbol}: "
                    f"Action={action}, Expiry={expiry_minutes}m, Stake={stake}, OrderData={order_data}"
                )
            except Exception as e:
                logger.exception(
                    f"[ExecutorManager] Broker execution failed for {symbol}: {e}"
                )
                traceback.print_exc()
                raise

            if not order_data or order_data.get("status") != "SUCCESS":
                error = order_data.get("error") if order_data else "empty broker response"
                raise RuntimeError(
                    f"FAIL-FAST: Broker rejected order for {symbol}: {error}"
                )

            # เมื่อยิงสำเร็จ ให้ลงทะเบียนเข้า OrderTracker ทันที และแสดงผลบน Console UI
            if order_data and order_data.get("status") == "SUCCESS":
                self.order_tracker.track_order(
                    order_data=order_data,
                    ai_decision=ai_decision,
                    broker_adapter=adapter_to_use
                )
                from monitoring.console_dashboard import ConsoleUI
                payload_id = ai_decision.get("ID") or ai_decision.get("payload_id") or ai_decision.get("id") or symbol
                order_id = order_data.get("order_id", "")
                ConsoleUI.show_order_placed(
                    payload_id=payload_id,
                    action=action,
                    expiry_minutes=expiry_minutes,
                    stake=stake,
                    order_id=order_id
                )

        executed_success = (
            order_data is not None and order_data.get("status") == "SUCCESS"
        )

        result = {
            "symbol": symbol,
            "action": action,
            "expiry_minutes": expiry_minutes,
            "confidence_score": confidence_score,
            "reason": reason_th or f"ส่งคำสั่ง {action} สำเร็จ",
            "should_execute": should_execute_order,
            "order_executed": executed_success,
            "order_data": order_data,
            "ai_decision": ai_decision,
            "risk_status": self.money_manager.get_risk_status()
        }

        logger.info(
            f"[ExecutorManager] {symbol} complete: "
            f"Action={result['action']} "
            f"Confidence={result['confidence_score']}% "
            f"Executed={result['order_executed']}"
        )
        return result

    @staticmethod
    def _halt_process(message: str) -> None:
        """Log a fatal trading error and terminate all threads immediately."""
        logger.error(message, exc_info=True)
        logging.shutdown()
        os._exit(1)

    def process_cycle_decision(
        self,
        symbol: str,
        prompt_filepath: str,
        payload: Optional[Dict[str, Any]] = None,
        broker_adapter: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Legacy single-symbol entry point (backward compatible).
        Uses concurrent dispatch internally with a single-item task list.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("FAIL-FAST: symbol must be a non-empty string")
        if not prompt_filepath or not isinstance(prompt_filepath, str):
            raise ValueError("FAIL-FAST: prompt_filepath must be a non-empty string")

        if not os.path.exists(prompt_filepath):
            raise FileNotFoundError(f"FAIL-FAST: Prompt file not found at {prompt_filepath}")

        try:
            decisions = self._dispatch_dual_decisions(
                [(symbol, prompt_filepath, None, None)]
            )
            ai_decision = decisions[symbol]
        except Exception as e:
            logger.exception(f"[ExecutorManager] AI analysis failed for {symbol}: {e}")
            traceback.print_exc()
            raise RuntimeError(
                f"FAIL-FAST: AI analysis failed for {symbol}; trading halted"
            ) from e

        return self._execute_single_decision(
            symbol=symbol,
            ai_decision=ai_decision,
            broker_adapter=broker_adapter or self._broker_adapter
        )
