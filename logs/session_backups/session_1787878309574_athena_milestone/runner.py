"""
FINALBOT Master Runner (Event-Driven Pipeline)
==============================================
สถาปัตยกรรมระบบ:
- Part 1 (Data Feed): ดึงแท่งเทียนสดจากโบรกเกอร์ บันทึก CSV 8 คอลัมน์ลงดิสก์
- Event-Driven Trigger (สะกิด): เมื่อ CSVWriter บันทึกไฟล์ลงดิสก์เสร็จ จะยิงสัญญาณ Path แจ้งเตือนทันที
- Part 2 (Data Evaluate): เมื่อได้รับสัญญาณ จะตื่นมาอ่านไฟล์ CSV จากดิสก์ (pd.read_csv) ทันที
  คำนวณอินดิเคเตอร์ 5 Engines และสร้างไฟล์ Prompt 99 บรรทัดส่งออกสู่ data_base/orchestrator/<SYMBOL>/
- Zero RAM Transfer: ไม่มีการส่งผ่านข้อมูลหรือ DataFrame ผ่านแรมระหว่าง Part 1 และ Part 2
"""

import os
import sys
import time
import signal
import logging
import concurrent.futures
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from monitoring.console_dashboard import ConsoleUI, logger, setup_logging, disable_quick_edit
from config_setting.config_loader import load_settings, get_symbols
from data_feed.bridge_adapter.broker_factory import BrokerFactory
from data_feed.data_adapter import DataAdapter
from data_evaluate.orchestrator import Orchestrator
from data_evaluate.news_calendar import ensure_calendar_news

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
            if hasattr(_ACTIVE_RUNNER, "executor_manager") and _ACTIVE_RUNNER.executor_manager:
                Orchestrator.unregister_listener(_ACTIVE_RUNNER.executor_manager.on_orchestrator_payload_saved)
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
        elif arg_lower in ("--mode", "-m") and i + 1 < len(args):
            val = args[i + 1].strip().lower()
            if val in ("ml", "ai"):
                return val
        elif arg_lower.startswith("--mode="):
            val = arg.split("=", 1)[1].strip().lower()
            if val in ("ml", "ai"):
                return val
    return None


class DataFeedRunner:
    """Master Event-Driven Coordinator for Part 1 Data Ingestion and Part 2 Evaluation."""

    def __init__(self, cli_mode: Optional[Any] = None):
        global _ACTIVE_RUNNER
        _ACTIVE_RUNNER = self

        self.settings = load_settings(reload=True)

        # CLI Mode Override
        selected_mode: Optional[str] = None
        if cli_mode is not None:
            if isinstance(cli_mode, bool):
                selected_mode = "ml" if cli_mode else "ai"
            elif isinstance(cli_mode, str):
                selected_mode = cli_mode.lower()
        else:
            selected_mode = parse_cli_mode()

        if selected_mode:
            if "ml_mode" not in self.settings:
                self.settings["ml_mode"] = {}
            if "ai_mode" not in self.settings:
                self.settings["ai_mode"] = {}
            if selected_mode == "ml":
                self.settings["ml_mode"]["enabled"] = True
                self.settings["ai_mode"]["enabled"] = False
            elif selected_mode == "ai":
                self.settings["ml_mode"]["enabled"] = False
                self.settings["ai_mode"]["enabled"] = True

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

        # 2. Load configured trading assets directly from SSOT (symbols.json)
        self.symbols: List[str] = get_symbols()
        ConsoleUI.show_asset_list(self.symbols)

        # 3. Show Time Sync & Offset
        ConsoleUI.show_time_offset(self.data_feed.time_calendar_mgr.time_offset)

        # 4. Display Account Balance
        try:
            balance = self.data_feed.get_balance()
            ConsoleUI.show_account_info(self.account_type, balance)
        except Exception as e:
            logger.exception("Failed to get account balance from broker")
            raise RuntimeError("FAIL-FAST: Failed to get balance from broker API") from e

        # 5. Initialize Part 2 Orchestrator (Loads Economic News Calendar automatically)
        self.orchestrator = Orchestrator(self.settings)

        # 5.1 Pre-warm and Test AI / ML Connections
        ml_cfg = self.settings.get("ml_mode", {})
        ai_cfg = self.settings.get("ai_mode", {})

        ml_enabled = bool(ml_cfg.get("enabled", True if not ai_cfg.get("enabled", False) else False))
        ai_enabled = bool(ai_cfg.get("enabled", False))

        if ml_enabled:
            from ai_analysis.machine_learning import MLDispatcher
            from ai_analysis.machine_learning.dual_brain import normalize_mode
            MLDispatcher.get_instance(self.settings)
            raw_model = str(ml_cfg.get("model", "LIGHTGBM_CHRONOS")).strip().upper()
            ml_model = normalize_mode(raw_model)
            if ml_model == "DUAL_BRAIN":
                display_str = f"{raw_model} [LightGBM + Chronos]"
            elif ml_model == "LIGHTGBM":
                display_str = f"{raw_model} [Single Model]"
            elif ml_model == "CHRONOS":
                display_str = f"{raw_model} [Single Model]"
            else:
                display_str = raw_model
            from monitoring.console_dashboard import thai_console_log
            thai_console_log(f"เชื่อมต่อสมองกล ML สำเร็จ (Model: {display_str} พร้อมใช้งาน)")
        elif ai_enabled:
            try:
                from ai_analysis.artificial_intelligence.ai_dispatcher import SystemPrompt
            except ImportError:
                from data_trade.ai_analysis.system_prompt import SystemPrompt
            ConsoleUI.show_ai_connection_attempt()
            SystemPrompt.prewarm_and_test_ai(self.symbols)
            provider = ai_cfg.get("provider", "GEMINI")
            gemini_model = ai_cfg.get("gemini_model", "gemini-3.5-flash-lite")
            from monitoring.console_dashboard import thai_console_log
            thai_console_log(f"เชื่อมต่อสมองกล AI สำเร็จ ({provider} - {gemini_model} พร้อมใช้งาน)")
        else:
            from ai_analysis.machine_learning import MLDispatcher
            from ai_analysis.machine_learning.dual_brain import normalize_mode
            MLDispatcher.get_instance(self.settings)
            raw_model = str(ml_cfg.get("model", "LIGHTGBM_CHRONOS")).strip().upper()
            ml_model = normalize_mode(raw_model)
            if ml_model == "DUAL_BRAIN":
                display_str = f"{raw_model} [LightGBM + Chronos]"
            elif ml_model == "LIGHTGBM":
                display_str = f"{raw_model} [Single Model]"
            elif ml_model == "CHRONOS":
                display_str = f"{raw_model} [Single Model]"
            else:
                display_str = raw_model
            from monitoring.console_dashboard import thai_console_log
            thai_console_log(f"เชื่อมต่อสมองกล ML สำเร็จ (Model: {display_str} พร้อมใช้งาน)")

        # 5.2 Initialize Part 3 ExecutorManager & Register Listener on Orchestrator
        from data_trade.executor_manager import ExecutorManager
        self.executor_manager = ExecutorManager(self.settings)
        self.executor_manager._broker_adapter = self.data_feed._broker
        Orchestrator.register_listener(self.executor_manager.on_orchestrator_payload_saved)

        # 5.3 Start Telegram AI Bridge in Background Thread (Chat with Athena via mobile)
        try:
            from monitoring.telegram_bridge import TelegramBridge
            self.telegram_bridge = TelegramBridge()
            telegram_thread = threading.Thread(
                target=self.telegram_bridge.start_polling,
                daemon=True,
                name="TelegramBridgeWorker"
            )
            telegram_thread.start()
            logger.info("[DataFeedRunner] Telegram AI Bridge started in background thread.")
        except Exception as e:
            logger.warning(f"[DataFeedRunner] Telegram AI Bridge note: {e}")

        # 6. Part 1 Commander: Historical Data Warm-Up (250 candles for M1, M5, M15)
        ConsoleUI.show_data_prep_start(self.symbols)
        self.data_feed.warmup_all_symbols(self.symbols)
        self.symbols = getattr(self.data_feed, "ready_symbols", self.symbols)
        ConsoleUI.show_data_prep_result(len(self.symbols), 0)

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
        self.data_feed.ensure_connected()
        if not self.symbols:
            return

        # 1. Part 1: Ingest candles → write CSV to disk → display UI prices & balance
        self.data_feed.ingest_cycle(self.symbols)

        # 2. Part 2: Read CSV from disk → evaluate 5 Engines → write Prompt 99 lines → display UI payload export
        self.orchestrator.evaluate_cycle(self.symbols)

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
                now = datetime.now(tz_thailand)
                target_time = now.replace(second=1, microsecond=500000)
                if target_time <= now:
                    target_time += timedelta(minutes=1)

                sleep_seconds = max(0.5, (target_time - now).total_seconds())
                time.sleep(sleep_seconds)


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
