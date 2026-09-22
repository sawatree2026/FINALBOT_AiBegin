"""
Executor Manager — Master Controller for Part 3 (Data Trade & Execution)
==========================================================================
หน้าที่: ผู้บัญชาการเทรดเท่านั้น (Trade & Risk Commander)

Flow:
1. รับสะกิดจาก Orchestrator Part 2 ผ่าน on_orchestrator_payload_saved()
2. รวบรวม pending symbols ใน thread-safe queue
3. flush → สั่ง SystemPrompt.process_ai_decisions_concurrent(tasks)
4. รับ decisions กลับ → วน ExecutionGate (confidence >= 70%) → BrokerExecutor

Concurrency: รองรับ 1 ถึง 10+ คู่เงินพร้อมกันโดยไม่รอคิว
"""

import os
import time
import logging
import traceback
import threading
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

from config_setting.config_loader import load_settings
from data_trade.ai_analysis.system_prompt import SystemPrompt
from data_trade.execution_gate.gate_controller import ExecutionGate
from data_trade.execution_gate.money_manager import MoneyManager
from data_trade.execution_gate.broker_executor import BrokerExecutor
from data_trade.execution_gate.order_tracker import OrderTracker

logger = logging.getLogger("ExecutorManager")


class ExecutorManager:
    """Central entry point for Part 3 trade decision and execution pipeline."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.settings = config or load_settings(reload=False)
        self.execution_gate = ExecutionGate(config=self.settings)
        self.money_manager = MoneyManager(config=self.settings)
        self.broker_executor = BrokerExecutor()
        self.order_tracker = OrderTracker(money_manager=self.money_manager)

        # ── Live Execution Flag ─────────────────────────────────────────────
        self.enable_live_execution: bool = bool(
            self.settings.get("data_trade", {}).get("enable_live_execution", True)
        )

        # ── Concurrent Dispatch State (thread-safe) ─────────────────────────
        self._pending_lock = threading.Lock()
        self._pending_tasks: Dict[str, str] = {}   # {symbol: prompt_filepath}
        self._flush_lock = threading.Lock()         # ป้องกัน concurrent flush ซ้อน
        self._broker_adapter: Optional[Any] = None  # เก็บ broker adapter ล่าสุด
        self._is_warmup_round: bool = False         # BOSS ORDER: Disabled warmup round

        logger.info(
            f"[ExecutorManager] Initialized | LiveExecution: {self.enable_live_execution} | "
            f"N-Symbol Concurrent Dispatch: ENABLED | Confidence Gate: >= 70% | "
            f"Warmup Round: DISABLED (เทรดตั้งแต่รอบแรก)"
        )


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
                    if isinstance(item, tuple) and len(item) == 2:
                        sym, fp = item
                        if sym and fp:
                            self._pending_tasks[sym] = fp
                    elif isinstance(item, dict):
                        sym = item.get("symbol")
                        fp = item.get("filepath") or item.get("prompt_filepath")
                        if sym and fp:
                            self._pending_tasks[sym] = fp
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
        prompt_filepath = prompt_filepath_or_batch
        if not symbol or not isinstance(symbol, str):
            logger.error(f"[ExecutorManager] Invalid symbol in nudge: {symbol!r}")
            return
        if not prompt_filepath or not isinstance(prompt_filepath, str):
            logger.error(f"[ExecutorManager] Invalid filepath for symbol {symbol}")
            return

        with self._pending_lock:
            self._pending_tasks[symbol] = prompt_filepath
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
                tasks: List[Tuple[str, str]] = list(self._pending_tasks.items())
                self._pending_tasks.clear()

            logger.info(
                f"[ExecutorManager] Concurrent flush: {len(tasks)} symbol(s) → "
                f"{[t[0] for t in tasks]}"
            )

            # ── AI / ML Decision Dispatch ───────────────────────────────────
            try:
                ml_cfg = self.settings.get("ml_mode", {})
                ai_cfg = self.settings.get("ai_mode", {})

                ml_enabled = bool(ml_cfg.get("enabled", True if not ai_cfg.get("enabled", False) else False))
                ai_enabled = bool(ai_cfg.get("enabled", False))

                if ml_enabled:
                    from ai_analysis.machine_learning import MLDispatcher
                    ml_disp = MLDispatcher.get_instance(self.settings)
                    decisions = {
                        sym: ml_disp.process_payload_file(sym, fpath)
                        for sym, fpath in tasks
                    }
                    from monitoring.console_dashboard import ConsoleUI
                    ConsoleUI.show_ai_analysis_complete(decisions)
                elif ai_enabled:
                    try:
                        from ai_analysis.artificial_intelligence.ai_dispatcher import SystemPrompt
                    except ImportError:
                        from data_trade.ai_analysis.system_prompt import SystemPrompt
                    decisions = SystemPrompt.process_ai_decisions_concurrent(tasks)
                else:
                    from ai_analysis.machine_learning import MLDispatcher
                    ml_disp = MLDispatcher.get_instance(self.settings)
                    decisions = {
                        sym: ml_disp.process_payload_file(sym, fpath)
                        for sym, fpath in tasks
                    }
                    from monitoring.console_dashboard import ConsoleUI
                    ConsoleUI.show_ai_analysis_complete(decisions)
            except Exception as e:
                logger.exception(
                    f"[ExecutorManager] decision dispatch crashed: {e}"
                )
                traceback.print_exc()
                decisions = {
                    sym: {
                        "symbol": sym,
                        "action": "WAIT",
                        "expiry_minutes": 1,
                        "confidence_score": 0,
                        "ai_final_reason_th": f"Decision crashed: {e}",
                        "engine_used": "FALLBACK_SAFE_WAIT"
                    }
                    for sym, _ in tasks
                }

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

    def _execute_single_decision(
        self,
        symbol: str,
        ai_decision: Dict[str, Any],
        broker_adapter: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        ประมวลผลการยิงออเดอร์ตามสัญญาณ AI / ML (Direct Execution)
        เงื่อนไข:
        1. ดึงยอดเงินจาก broker_adapter (ถ้าไม่มีใช้ 999999.0)
        2. ตรวจสอบ money_manager.can_trade(symbol=symbol, balance=balance)
        3. ถ้า not can_trade -> ส่งผล BLOCKED_BY_RISK ทันที
        4. ถ้า action in ("CALL", "PUT") -> ยิงออเดอร์ทันที (หาก enable_live_execution=True)
        5. เมื่อยิงสำเร็จ -> บันทึกเข้า order_tracker เพื่อติดตามและแจ้ง money_manager เมื่อจบสัญญา
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

        # ── Step 1: ดึงยอดเงินคงเหลือจาก Broker ──────────────────────────────
        balance = 999999.0
        adapter_to_use = broker_adapter or self._broker_adapter
        if adapter_to_use is not None:
            try:
                if hasattr(adapter_to_use, "get_balance"):
                    balance = float(adapter_to_use.get_balance())
                elif hasattr(adapter_to_use, "api") and hasattr(adapter_to_use.api, "get_balance"):
                    balance = float(adapter_to_use.api.get_balance())
            except Exception as e:
                logger.warning(f"[ExecutorManager] Could not retrieve balance from broker: {e}")
                balance = 999999.0

        # ── Step 2: ตรวจสอบ Risk Gate (ห้ามยิงซ้ำคู่เดิม / TP / SL / Balance) ────
        can_trade, risk_reason = self.money_manager.can_trade(symbol=symbol, balance=balance)
        if not can_trade:
            logger.info(f"[ExecutorManager] {symbol} blocked by risk gate: {risk_reason}")
            return {
                "symbol": symbol,
                "action": "BLOCKED_BY_RISK",
                "expiry_minutes": expiry_minutes,
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
                "expiry_minutes": expiry_minutes,
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

            if adapter_to_use is None:
                import time
                from datetime import timezone, timedelta
                tz_thailand = timezone(timedelta(hours=7))
                sim_timestamp = datetime.now(tz_thailand).isoformat()
                sim_order_id = f"SIM_{int(time.time() * 1000)}"
                logger.warning(
                    f"[ExecutorManager] No broker_adapter — simulated execution for {symbol} (ID: {sim_order_id})"
                )
                order_data = {
                    "status": "SIMULATED",
                    "order_id": sim_order_id,
                    "symbol": symbol,
                    "action": action,
                    "stake": stake,
                    "expiry_minutes": expiry_minutes,
                    "timestamp": sim_timestamp,
                    "protocol": "SIMULATED",
                    "error": None
                }
            else:
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

            # เมื่อยิงสำเร็จ ให้ลงทะเบียนเข้า OrderTracker ทันที และแสดงผลบน Console UI
            if order_data and order_data.get("status") in ("SUCCESS", "SIMULATED"):
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
            order_data is not None and order_data.get("status") in ("SUCCESS", "SIMULATED")
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
            ml_cfg = self.settings.get("ml_mode", {})
            ai_cfg = self.settings.get("ai_mode", {})

            ml_enabled = bool(ml_cfg.get("enabled", True if not ai_cfg.get("enabled", False) else False))
            ai_enabled = bool(ai_cfg.get("enabled", False))

            if ml_enabled:
                from ai_analysis.machine_learning import MLDispatcher
                ml_disp = MLDispatcher.get_instance(self.settings)
                ai_decision = ml_disp.process_payload_file(symbol, prompt_filepath)
            elif ai_enabled:
                try:
                    from ai_analysis.artificial_intelligence.ai_dispatcher import SystemPrompt
                except ImportError:
                    from data_trade.ai_analysis.system_prompt import SystemPrompt
                decisions = SystemPrompt.process_ai_decisions_concurrent([(symbol, prompt_filepath)])
                ai_decision = decisions.get(symbol, {
                    "symbol": symbol, "action": "WAIT",
                    "expiry_minutes": 1, "confidence_score": 0,
                    "ai_final_reason_th": "AI decision missing from concurrent result",
                    "engine_used": "FALLBACK_SAFE_WAIT"
                })
            else:
                from ai_analysis.machine_learning import MLDispatcher
                ml_disp = MLDispatcher.get_instance(self.settings)
                ai_decision = ml_disp.process_payload_file(symbol, prompt_filepath)
        except Exception as e:
            logger.exception(f"[ExecutorManager] AI analysis failed for {symbol}: {e}")
            traceback.print_exc()
            ai_decision = {
                "symbol": symbol, "action": "WAIT",
                "expiry_minutes": 1, "confidence_score": 0,
                "ai_final_reason_th": f"AI ขัดข้อง ({e})",
                "engine_used": "FALLBACK_SAFE_WAIT"
            }

        return self._execute_single_decision(
            symbol=symbol,
            ai_decision=ai_decision,
            broker_adapter=broker_adapter or self._broker_adapter
        )


