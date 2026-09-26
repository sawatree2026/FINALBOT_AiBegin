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
from config_setting.mode_loader import (
    normalize_mode,
    normalize_evaluate_mode,
    load_broker_adapter,
    load_data_feed,
    load_orchestrator,
    load_decision_manager,
    load_executor_manager,
    mode_output_dir,
)


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

        mode_root = os.path.join("data_base", self.active_mode)
        self.settings.setdefault("data_feed", {}).setdefault("csv_manager", {})["base_dir"] = os.path.join(mode_root, "output_feed")
        self.settings.setdefault("data_evaluate", {})["output_dir"] = os.path.join(mode_root, "output_evaluate")
        self.settings.setdefault("data_decision", {})["output_dir"] = os.path.join(mode_root, "output_decision")
        self.settings["data_decision"]["strategies_output_dir"] = os.path.join(mode_root, "output_decision")
        self.settings["data_decision"]["ai_output_dir"] = os.path.join(mode_root, "output_decision")
        self.settings["data_decision"]["ml_output_dir"] = os.path.join(mode_root, "output_decision")
        self.settings.setdefault("data_trade", {})["trade_history_file"] = os.path.join(mode_root, "output_trade", "trades_history.csv")

        self.account_type = self.settings.get("account", {}).get("account_type", "PRACTICE")

        # 1. Initialize Part 1 Commander (DataAdapter via BrokerFactory)
        ConsoleUI.show_connection_attempt()
        self.data_feed = load_data_feed(self.active_mode, self.settings)
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
        self.settings["data_evaluate"]["output_dir"] = mode_output_dir(
            self.settings, self.active_mode
        )
        self.orchestrator = load_orchestrator(self.active_mode, self.settings)

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
        self.decision_manager = load_decision_manager(self.active_mode, self.settings)
        self.executor_manager = load_executor_manager(
            self.active_mode,
            self.settings,
            broker_adapter=getattr(self.data_feed, "_broker", None)
        )

        # 6. Part 1 Commander: Historical Data Warm-Up (250 candles for M1, M5, M15)
        ConsoleUI.show_data_prep_start(self.symbols)
        self.data_feed.warmup_all_symbols(self.symbols)
        self.symbols = getattr(self.data_feed, "ready_symbols", self.symbols)
        ConsoleUI.show_data_prep_result(len(self.symbols), 0)

    def _acquire_single_instance_lock(self) -> None:
        """Prevent two runner processes from fetching the same market simultaneously."""
        lock_path = os.path.join("logs", "runner.lock")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        if not os.path.exists(lock_path) or os.path.getsize(lock_path) == 0:
            try:
                with open(lock_path, "wb") as f:
                    f.write(b"1")
            except Exception:
                pass
        try:
            lock_file = open(lock_path, "r+b", buffering=0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._runner_lock_file = lock_file
            import atexit
            atexit.register(self._release_single_instance_lock)
            logger.info("[DataFeedRunner] Single-instance lock acquired: %s", lock_path)
        except Exception:
            try:
                if 'lock_file' in locals() and lock_file:
                    lock_file.close()
            except Exception:
                pass
            raise RuntimeError(
                f"FAIL-FAST: Another runner.py instance is already active ({lock_path}). Please close existing process first."
            ) from None

    def _release_single_instance_lock(self) -> None:
        if getattr(self, "_runner_lock_file", None):
            try:
                if os.name == "nt":
                    import msvcrt
                    self._runner_lock_file.seek(0)
                    msvcrt.locking(self._runner_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                self._runner_lock_file.close()
            except Exception:
                pass
            self._runner_lock_file = None

    def _countdown_to_first_candle(self):
        """Sleep until the next completed S30 boundary (:01.500 or :31.500)."""
        tz_thailand = timezone(timedelta(hours=7))
        now = datetime.now(tz_thailand)

        candidates = []
        for second in (1, 31):
            candidate = now.replace(second=second, microsecond=500000)
            if candidate > now:
                candidates.append(candidate)
        if not candidates:
            base = now + timedelta(minutes=1)
            candidates.append(base.replace(second=1, microsecond=500000))
        target_time = min(candidates)

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
            if isinstance(ingest_result, dict) and "ready_symbols" in ingest_result:
                ready_symbols = list(ingest_result["ready_symbols"])
            elif isinstance(ingest_result, dict):
                ready_symbols = [s for s, p in ingest_result.items() if p is not None]
            else:
                ready_symbols = list(ingest_result or [])
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
        """Main Loop: run after every completed 30-second S30 candle."""
        self._countdown_to_first_candle()
        tz_thailand = timezone(timedelta(hours=7))

        while True:
            try:
                self.run_cycle()

                # Sleep directly to the next S30 boundary (:01.500 or :31.500).
                now = datetime.now(tz_thailand)
                next_minute = now.replace(second=0, microsecond=0)
                candidates = []
                for second in (1, 31):
                    candidate = next_minute.replace(second=second, microsecond=500000)
                    if candidate > now:
                        candidates.append(candidate)
                if not candidates:
                    base = next_minute + timedelta(minutes=1)
                    candidates.append(base.replace(second=1, microsecond=500000))
                target_time = min(candidates)

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
