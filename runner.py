"""
FINALBOT Master Runner (Event-Driven Pipeline)
==============================================
สถาปัตยกรรมระบบ:
- Part 1 (Data Feed): ดึงข้อมูลราคาดิบและเขียนลง data_base/output_feed
- Part 2 (Data Evaluate): อ่าน output_feed จาก SSD คำนวณและเขียน Payload ลง output_evaluate
- Part 3 (Data Decision): อ่าน Payload จาก SSD วิเคราะห์ AI/กลยุทธ์ และเขียน output_decision
- Part 4 (Data Trade): อ่าน output_decision จาก SSD ตรวจสอบความปลอดภัยและส่งคำสั่ง
- Zero RAM Transfer: RAM ใช้ได้เฉพาะภายในแต่ละ Part; boundary ระหว่าง Part ใช้ไฟล์บน SSD
"""

import os
import sys
import time
import signal
import logging
import msvcrt
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from monitoring.console_dashboard import ConsoleUI, logger, setup_logging, disable_quick_edit
from config_setting.config_loader import load_settings, get_symbols
from data_feed.bridge_adapter.broker_factory import BrokerFactory
from data_feed.data_adapter import DataAdapter
from data_evaluate.mode_loader import (
    mode_output_dir,
    normalize_evaluate_mode,
    load_orchestrator_class,
)
from data_decision.decision_manager import DecisionManager

setup_logging()
disable_quick_edit()

# Global reference for signal handling and instant OS-level hard termination
_ACTIVE_RUNNER: Optional["DataFeedRunner"] = None


def graceful_exit(signum=None, frame=None):
    """Handle exit signals cleanly and immediately hard exit the process."""
    global _ACTIVE_RUNNER
    try:
        ConsoleUI.show_stopping()
    except Exception:
        pass

    if _ACTIVE_RUNNER is not None:
        try:
            if hasattr(_ACTIVE_RUNNER, "data_feed") and _ACTIVE_RUNNER.data_feed:
                _ACTIVE_RUNNER.data_feed.disconnect()
        except Exception:
            pass

    # Instant hard exit at the OS level (0.00s) to kill all background threads cleanly
    os._exit(0)


def parse_cli_mode() -> Optional[str]:
    """
    Parse CLI arguments for dual engine mode:
    --mode ml / --mode ML / --ml / -ml ➡️ 'ml' (ml_mode.enabled = True, ai_mode.enabled = False)
    --mode ai / --mode AI / --ai / -ai ➡️ 'ai' (ml_mode.enabled = False, ai_mode.enabled = True)
    """
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        arg_lower = arg.lower()
        if arg_lower in ("--ml", "-ml"):
            return "ml"
        elif arg_lower in ("--ai", "-ai"):
            return "ai"
        elif arg_lower in ("--strategies", "--strategy", "-strategies"):
            return "strategies"
        elif arg_lower in ("--mode", "-m") and i + 1 < len(args):
            val = args[i + 1].strip().lower()
            if val in ("ml", "ai", "strategies", "strategy"):
                return val
        elif arg_lower.startswith("--mode="):
            val = arg.split("=", 1)[1].strip().lower()
            if val in ("ml", "ai", "strategies", "strategy"):
                return val
    return None


class DataFeedRunner:
    """Master coordinator for the four Parts with SSD-only handoffs."""

    def __init__(self, cli_mode: Optional[Any] = None):
        global _ACTIVE_RUNNER
        _ACTIVE_RUNNER = self

        self.settings = load_settings(reload=True)
        self._cycle_lock = threading.Lock()
        self._runner_lock_file = None
        self._acquire_single_instance_lock()

        # CLI Mode Override. Exactly one evaluation mode is active per process.
        configured_mode = self.settings.get("active_mode", "strategies_mode")
        if isinstance(cli_mode, bool):
            configured_mode = "ml_mode" if cli_mode else "ai_mode"
        elif cli_mode is not None:
            configured_mode = cli_mode
        selected_mode: str = normalize_evaluate_mode(configured_mode)
        cli_selected = parse_cli_mode() if cli_mode is None else cli_mode
        if cli_selected is not None:
            selected_mode = normalize_evaluate_mode(cli_selected)
        self.active_mode = selected_mode
        self.settings["active_mode"] = selected_mode

        self.account_type = self.settings.get("account", {}).get("account_type", "PRACTICE")

        # 1. Initialize Part 1 Commander (DataAdapter via BrokerFactory)
        ConsoleUI.show_connection_attempt()
        self.data_feed: DataAdapter = BrokerFactory.create_broker(config=self.settings)
        if not self.data_feed.connected:
            ConsoleUI.show_connection_failed()
            os._exit(1)
        ConsoleUI.show_connection_success()

        # 1.1 Dynamically populate active IDs into OP_code.ACTIVES for all broker assets
        try:
            import iqoptionapi.constants as OP_code
            if hasattr(self.data_feed, "api") and self.data_feed.api:
                init_data = self.data_feed.api.get_all_init() or {}
                for cat in ["turbo", "binary"]:
                    for aid, ainfo in init_data.get("result", {}).get(cat, {}).get("actives", {}).items():
                        name = ainfo.get("name", "").replace("front.", "")
                        if name:
                            OP_code.ACTIVES[name] = int(aid)
        except Exception as e:
            logger.warning(f"[DataFeedRunner] Dynamic active registration note: {e}")

        # Display symbol mode sequence
        symbol_mode = str(self.settings.get("symbol_mode", "bot")).strip().lower()
        ConsoleUI.show_sequence_order_2(symbol_mode)
        if symbol_mode == "bot":
            from config_setting.symbols_selection import run_selector
            run_selector(data_adapter=self.data_feed, silent=True)
        ConsoleUI.show_sequence_order_3(symbol_mode)

        from config_setting.config_loader import get_symbols_with_payouts
        self.symbols, self.symbol_payouts = get_symbols_with_payouts()
        ConsoleUI.show_asset_list(self.symbols, payouts=self.symbol_payouts)

        # 3. Show Time Sync & Offset
        ConsoleUI.show_time_offset(self.data_feed.time_calendar_mgr.time_offset)

        # 4. Display Account Balance
        try:
            balance = self.data_feed.get_balance()
            ConsoleUI.show_account_info(self.account_type, balance)
        except Exception as e:
            logger.exception("Failed to get account balance from broker")
            raise RuntimeError("FAIL-FAST: Failed to get balance from broker API") from e

        # 5. Initialize the mode-specific Part 2 Orchestrator.
        orchestrator_class = load_orchestrator_class(self.active_mode)
        self.settings["data_evaluate"]["output_dir"] = mode_output_dir(
            self.settings, self.active_mode
        )
        self.orchestrator = orchestrator_class(self.settings)

        # 5.1 Pre-warm and Test AI / ML Connections
        ml_enabled = self.active_mode == "ml_mode"
        ai_enabled = self.active_mode == "ai_mode"
        strategies_enabled = self.active_mode == "strategies_mode"

        if ml_enabled:
            from data_decision.ai_analysis.machine_learning.ml_dispatcher import MLDispatcher
            MLDispatcher.get_instance(self.settings)
            from monitoring.console_dashboard import thai_console_log
            thai_console_log("เชื่อมต่อ ML/Chronos ใน data_decision สำเร็จ")
        if ai_enabled:
            from data_decision.ai_analysis.artificial_intelligence.ai_dispatcher import SystemPrompt
            ConsoleUI.show_ai_connection_attempt()
            SystemPrompt.prewarm_and_test_ai(self.symbols)
            ai_cfg = self.settings.get("ai_mode", {})
            provider = ai_cfg.get("provider", "GEMINI")
            primary_model = ai_cfg.get("primary_model") or ai_cfg.get("gemini_model", "gemini-3.5-flash-lite")
            secondary_model = ai_cfg.get("secondary_model", "gemini-3.1-flash-lite")
            from monitoring.console_dashboard import thai_console_log
            thai_console_log(f"เชื่อมต่อสมองกล AI สำเร็จ ({provider} - {primary_model} / {secondary_model} พร้อมใช้งาน)")
        if strategies_enabled:
            from monitoring.console_dashboard import thai_console_log
            thai_console_log("เปิดใช้งาน Strategies mode")

        # 5.2 Initialize Part 3 DecisionManager and Part 4 Trade Manager.
        # Parts exchange only durable files on SSD; no payload listener is registered.
        self.decision_manager = DecisionManager(self.settings)
        from data_trade.executor_manager import ExecutorManager
        self.executor_manager = ExecutorManager(self.settings)
        self.executor_manager._broker_adapter = self.data_feed._broker

        # 6. Part 1 Commander: Historical Data Warm-Up (250 candles for M1, M5, M15)
        ConsoleUI.show_data_prep_start(self.symbols)
        self.data_feed.warmup_all_symbols(self.symbols)
        self.symbols = getattr(self.data_feed, "ready_symbols", self.symbols)
        ConsoleUI.show_data_prep_result(len(self.symbols), 0)

    def _acquire_single_instance_lock(self) -> None:
        """Prevent two runner processes from fetching the same market simultaneously."""
        lock_path = os.path.join("logs", "runner.lock")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        lock_file = open(lock_path, "a+", encoding="ascii")
        lock_file.seek(0)
        try:
            lock_file.write("1")
            lock_file.flush()
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            lock_file.close()
            raise RuntimeError(
                f"FAIL-FAST: Another runner.py instance is already active ({lock_path})"
            ) from exc
        self._runner_lock_file = lock_file
        logger.info("[DataFeedRunner] Single-instance lock acquired: %s", lock_path)

    def _countdown_to_first_candle(self):
        """Sleep directly until the first completed candle minute boundary (:01.500)."""
        tz_thailand = timezone(timedelta(hours=7))
        now = datetime.now(tz_thailand)

        target_time = now.replace(second=1, microsecond=500000)
        if now >= target_time:
            target_time += timedelta(minutes=1)

        total_wait = (target_time - now).total_seconds()
        target_str = target_time.strftime("%H:%M:%S")

        ConsoleUI.show_countdown(f"{total_wait:.1f}", target_str)
        if total_wait > 0:
            time.sleep(total_wait)

    def run_cycle(self):
        """Execute one complete data ingestion and evaluation cycle for all symbols."""
        if not self._cycle_lock.acquire(blocking=False):
            logger.warning("[DataFeedRunner] Skipping overlapping cycle")
            return

        cycle_started = time.perf_counter()
        self.data_feed.ensure_connected()
        if not self.symbols:
            self._cycle_lock.release()
            return
        try:
            logger.info("[DataFeedRunner] Cycle start: symbols=%d", len(self.symbols))

            ingest_started = time.perf_counter()
            ingest_result = self.data_feed.ingest_cycle(self.symbols)
            ready_symbols = list(ingest_result.get("ready_symbols", []))
            if not ready_symbols:
                raise RuntimeError("FAIL-FAST: No symbols produced fresh S30/M1/M5 CSV files")
            ingest_elapsed = time.perf_counter() - ingest_started

            logger.info(
                "[DataFeedRunner] Ingest complete: %.3fs; Part 2 will read feed CSV files from disk",
                ingest_elapsed,
            )

            evaluate_started = time.perf_counter()
            self.orchestrator.evaluate_cycle(ready_symbols)
            evaluate_elapsed = time.perf_counter() - evaluate_started
            decision_started = time.perf_counter()
            self.decision_manager.process_latest(ready_symbols)
            self.executor_manager.process_decision_files(ready_symbols)
            logger.info(
                "[DataFeedRunner] Evaluation/decision/trade complete: %.3fs/%.3fs; cycle_total=%.3fs",
                evaluate_elapsed,
                time.perf_counter() - decision_started,
                time.perf_counter() - cycle_started,
            )
        finally:
            self._cycle_lock.release()

    def start(self):
        """Main Loop: Runs strictly at each minute boundary (:01.500) and sleeps between intervals."""
        self._countdown_to_first_candle()
        tz_thailand = timezone(timedelta(hours=7))

        while True:
            try:
                self.run_cycle()

                # Sleep directly to next minute boundary (:01.500)
                now = datetime.now(tz_thailand)
                target_time = now.replace(second=1, microsecond=500000)
                if target_time <= now:
                    target_time += timedelta(minutes=1)

                sleep_seconds = max(0.5, (target_time - now).total_seconds())
                time.sleep(sleep_seconds)

            except KeyboardInterrupt:
                graceful_exit()
            except Exception as e:
                logger.exception(f"[DataFeedRunner] Error in runner execution loop: {e}")
                graceful_exit()


# Alias for compatibility with main.py
PureAIRunner = DataFeedRunner


if __name__ == "__main__":
    # Register signal handlers for clean OS-level hard termination
    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, graceful_exit)

    runner = DataFeedRunner()
    runner.start()
