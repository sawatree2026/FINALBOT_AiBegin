"""
Advanced Analytics Dashboard

Compare strategies, analyze correlation, ML metrics.
"""

import sys
import os
import threading
import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

class SafeStreamWrapper:
    def __init__(self, original_stream):
        self.original_stream = original_stream
        self.encoding = getattr(original_stream, 'encoding', None) or 'utf-8'

    def write(self, data):
        try:
            self.original_stream.write(data)
        except Exception:
            try:
                # Force fallback to pure ASCII with backslashreplace
                safe_data = data.encode('ascii', errors='backslashreplace').decode('ascii')
                self.original_stream.write(safe_data)
            except Exception:
                pass

    def flush(self):
        if hasattr(self.original_stream, 'flush'):
            self.original_stream.flush()

    def __getattr__(self, attr):
        return getattr(self.original_stream, attr)

class AutoFlushRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that automatically flushes to disk after every record (Zero Log Buffer Loss)."""
    def emit(self, record):
        super().emit(record)
        self.flush()

class ExactLevelFilter(logging.Filter):
    """Filter that allows log records matching a specific level range, suppressing SEC_TRACK."""
    def __init__(self, min_level: int, max_level: int = logging.CRITICAL + 10):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "[SEC_TRACK]" in msg:
            return False
        return self.min_level <= record.levelno <= self.max_level

class ConsoleHandler(logging.StreamHandler):
    """Handler for Terminal console output, filtering out [SEC_TRACK] messages."""
    def __init__(self, stream=None):
        super().__init__(stream or sys.stdout)
        self.addFilter(ExactLevelFilter(min_level=logging.INFO))

_PRINT_LOCK = threading.Lock()
_LOGGING_INITIALIZED = False

def setup_logging():
    global _LOGGING_INITIALIZED
    if _LOGGING_INITIALIZED:
        return
    
    sys.stdout = SafeStreamWrapper(sys.stdout)
    sys.stderr = SafeStreamWrapper(sys.stderr)

    # Base Log Directories
    feed_log_dir = "logs/logs_data_feed"
    eval_log_dir = "logs/logs_data_evaluate"

    feed_errors_dir = os.path.join(feed_log_dir, "errors")
    feed_warnings_dir = os.path.join(feed_log_dir, "warnings")
    fallback_dir = os.path.join(feed_log_dir, "fallback")

    eval_errors_dir = os.path.join(eval_log_dir, "errors")
    eval_warnings_dir = os.path.join(eval_log_dir, "warnings")

    os.makedirs(feed_errors_dir, exist_ok=True)
    os.makedirs(feed_warnings_dir, exist_ok=True)
    os.makedirs(fallback_dir, exist_ok=True)
    os.makedirs(eval_errors_dir, exist_ok=True)
    os.makedirs(eval_warnings_dir, exist_ok=True)

    max_bytes = 50 * 1024 * 1024  # 50 MB
    backup_count = 1000

    feed_error_log_path = os.path.join(feed_errors_dir, "error.log")
    feed_warning_log_path = os.path.join(feed_warnings_dir, "warning.log")
    fallback_log_path = os.path.join(fallback_dir, "fallback.log")

    eval_error_log_path = os.path.join(eval_errors_dir, "error.log")
    eval_warning_log_path = os.path.join(eval_warnings_dir, "warning.log")

    formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s')

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    # Part 2 module identifier filter
    part2_names = (
        "data_evaluate",
        "Orchestrator",
        "AdvancedToolsManager",
        "IndicatorStore",
        "MarketStateClassifier",
        "TrendEngine",
        "StrengthEngine",
        "VolatilityEngine",
        "StructureEngine",
        "MTFEngine",
        "ExplainabilityEngine",
        "LiquidityEngine",
        "NoiseDetector",
        "ProbabilityEstimator",
        "SignalThrottle",
        "ContextSynthesizer",
        "MarketStructureEngine",
        "MarketPressureAnalyzer",
    )

    class Part2Filter(logging.Filter):
        def filter(self, record):
            return any(record.name.startswith(p) for p in part2_names)

    class Part1Filter(logging.Filter):
        def filter(self, record):
            return not any(record.name.startswith(p) for p in part2_names)

    # ── Part 1 Handlers (logs_data_feed) ──────────────────────────────────
    feed_error_handler = AutoFlushRotatingFileHandler(
        feed_error_log_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )
    feed_error_handler.setLevel(logging.ERROR)
    feed_error_handler.setFormatter(formatter)
    feed_error_handler.addFilter(ExactLevelFilter(min_level=logging.ERROR))
    feed_error_handler.addFilter(Part1Filter())
    root_logger.addHandler(feed_error_handler)

    feed_warning_handler = AutoFlushRotatingFileHandler(
        feed_warning_log_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )
    feed_warning_handler.setLevel(logging.WARNING)
    feed_warning_handler.setFormatter(formatter)
    feed_warning_handler.addFilter(ExactLevelFilter(min_level=logging.WARNING, max_level=logging.WARNING))
    feed_warning_handler.addFilter(Part1Filter())
    root_logger.addHandler(feed_warning_handler)

    # Fallback Handler: fallback/fallback.log (WARNING+ for REST fallback events)
    fallback_handler = AutoFlushRotatingFileHandler(
        fallback_log_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )
    fallback_handler.setLevel(logging.WARNING)
    fallback_handler.setFormatter(formatter)

    class FallbackFilter(logging.Filter):
        """Only log records that contain [FALLBACK] in the message."""
        def filter(self, record):
            return "[FALLBACK]" in record.getMessage()
    fallback_handler.addFilter(FallbackFilter())
    root_logger.addHandler(fallback_handler)

    # ── Part 2 Handlers (logs_data_evaluate) ──────────────────────────────
    eval_error_handler = AutoFlushRotatingFileHandler(
        eval_error_log_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )
    eval_error_handler.setLevel(logging.ERROR)
    eval_error_handler.setFormatter(formatter)
    eval_error_handler.addFilter(ExactLevelFilter(min_level=logging.ERROR))
    eval_error_handler.addFilter(Part2Filter())
    root_logger.addHandler(eval_error_handler)

    eval_warning_handler = AutoFlushRotatingFileHandler(
        eval_warning_log_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )
    eval_warning_handler.setLevel(logging.WARNING)
    eval_warning_handler.setFormatter(formatter)
    eval_warning_handler.addFilter(ExactLevelFilter(min_level=logging.WARNING, max_level=logging.WARNING))
    eval_warning_handler.addFilter(Part2Filter())
    root_logger.addHandler(eval_warning_handler)

    finalbot_logger = logging.getLogger("FINALBOT")
    finalbot_logger.setLevel(logging.INFO)
    finalbot_logger.handlers.clear()
    finalbot_logger.propagate = True

    _LOGGING_INITIALIZED = True

def thai_console_log(msg: str):
    tz_thailand = timezone(timedelta(hours=7))
    thai_time_str = datetime.now(tz_thailand).strftime('%H:%M:%S')
    try:
        with _PRINT_LOCK:
            print(f"{thai_time_str} - {msg}")
            # Only flush if it doesn't cause error
            try:
                sys.stdout.flush()
            except (OSError, IOError):
                pass  # Ignore flush errors
        # Also log to file to avoid silent failures
        logging.getLogger("FINALBOT").info(msg)
    except Exception as e:
        # Zero Tolerance: console errors must be logged
        logging.getLogger("FINALBOT").error(f"Console output error: {e}")
        raise RuntimeError(f"Console output failed: {e}")

def disable_quick_edit():
    """Disable Windows Console QuickEdit mode to prevent accidental freeze on click."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE = -10
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
                # ENABLE_QUICK_EDIT_MODE = 0x0040, ENABLE_EXTENDED_FLAGS = 0x0080
                ENABLE_QUICK_EDIT_MODE = 0x0040
                ENABLE_EXTENDED_FLAGS = 0x0080
                new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
                kernel32.SetConsoleMode(h_stdin, new_mode)
        except Exception as e:
            logging.getLogger("FINALBOT").warning(f"Could not disable QuickEdit Mode: {e}")

logger = logging.getLogger("FINALBOT")


class ConsoleUI:
    """Handles all console UI formatting and printing."""
    
    @staticmethod
    def show_startup():
        thai_console_log("FINALBOT Running")

    @staticmethod
    def show_symbols_loaded(symbols):
        thai_console_log(f"คู่เงิน ({len(symbols)}): {', '.join(symbols)}")

    @staticmethod
    def show_live_mode_start():
        thai_console_log("เริ่ม Live Mode — วิเคราะห์ทุกแท่ง M1 (Ctrl+C หยุด)")

    @staticmethod
    def show_connection_attempt():
        thai_console_log("กำลังเชื่อมต่อโบรกเกอร์  | IQ Option")

    @staticmethod
    def show_connection_success():
        thai_console_log("เชื่อมต่อ IQ Option สำเร็จ")

    @staticmethod
    def show_connection_failed():
        thai_console_log("เชื่อมต่อ IQ Option ล้มเหลว")

    @staticmethod
    def show_account_info(account_type, balance):
        thai_console_log(f"บัญชี {account_type} | ยอดเงิน: ${balance:.2f}")

    @staticmethod
    def show_time_offset(offset):
        thai_console_log(f"Time Sync : {offset:.3f}s")

    @staticmethod
    def show_trading_mode(mode, stake, profit_pct, loss_pct, max_conc, trade_hours):
        thai_console_log(f"Trading Mode: {mode} [Stake:{stake}][Profit:{profit_pct}%][Loss:{loss_pct}%][Orderlimit:{max_conc}][Time:{trade_hours}]")

    @staticmethod
    def show_ai_checking():
        thai_console_log("ตรวจเช็คความพร้อม AI")

    @staticmethod
    def show_ai_connection_attempt():
        thai_console_log("กำลังทดสอบการเชื่อมต่อสมองกล AI  | Google Gemini")

    @staticmethod
    def show_ai_connection_success(channel_count: int, model_name: str = "gemini-3.5-flash-lite"):
        thai_console_log(f"เชื่อมต่อ AI สำเร็จ ({model_name} | พร้อมใช้งาน {channel_count} ท่อสัญญาณ)")

    @staticmethod
    def show_ai_failed():
        thai_console_log("เชื่อมต่อ AI ล้มเหลว")

    @staticmethod
    def show_ai_prompt_sent(count=0, skipped_symbols=None):
        if skipped_symbols is None:
            skipped_symbols = []
        
        msg = f"✅ ส่งคำสั่ง Prompt เข้า DeepSeek Agent สำเร็จ ({count} รายการ)!"
        if skipped_symbols:
            msg += f" | ⚠️ ข้ามรอบนี้: {', '.join(skipped_symbols)} (ทำงานค้างอยู่)"
        
        thai_console_log(msg)

    @staticmethod
    def show_ai_reply(reply):
        thai_console_log(f'"{reply}"')

    @staticmethod
    def show_asset_list(symbols):
        thai_console_log(f"ตรวจพบรายการสินทรัพย์ : {', '.join(symbols)}")

    @staticmethod
    def show_data_prep_start(symbols):
        thai_console_log(f"กำลังเตรียมข้อมูลสินทรัพย์ {len(symbols)} รายการ : {', '.join(symbols)}")

    @staticmethod
    def show_data_prep_result(ready_count, not_ready_count=0):
        if not_ready_count > 0:
            thai_console_log(f"ตรวจสอบข้อมูลแท่งเทียนสมบูรณ์ (M1/M5/M15 ครบ 250 แท่ง) : พร้อม {ready_count} รายการ (ไม่สมบูรณ์ {not_ready_count} รายการ)")
        else:
            thai_console_log(f"ตรวจสอบข้อมูลแท่งเทียนสมบูรณ์ (M1/M5/M15 ครบ 250 แท่ง) : พร้อม {ready_count} รายการ")

    @staticmethod
    def show_mode_summary(stake, profit_pct, loss_pct, max_conc, trade_hours):
        pass # Merged into show_trading_mode

    @staticmethod
    def show_news_status(msg):
        thai_console_log(msg)
    
    @staticmethod
    def show_calendar_status(msg):
        thai_console_log(msg)
    
    @staticmethod
    def show_balance(balance):
        thai_console_log(f"ยอดเงินในระบบ: ${balance:.2f}")

    @staticmethod
    def show_countdown(remaining, target_str):
        thai_console_log(f"เข้าสู่การวิเคราะห์สัญญาณในอีก {remaining} วินาที  (เริ่ม {target_str})")

    @staticmethod
    def show_insight(source, action, confidence):
        thai_console_log(f"{source}: {action} ({confidence}%)")

    @staticmethod
    def show_order_execution(action, symbol, expiry_time):
        thai_console_log(f"ยิงออเดอร์ {action} {symbol} ({expiry_time} นาที)")

    @staticmethod
    def show_order_success(order_id):
        thai_console_log(f"   └─ ออเดอร์เข้าสำเร็จ (ID: {order_id})")

    @staticmethod
    def show_order_failed(symbol, reason):
        thai_console_log(f"Execution failed for {symbol}: {reason}")

    @staticmethod
    def show_signal_only(action, symbol, expiry_time, mode):
        thai_console_log(f"[SIGNAL ONLY] {action} {symbol} ({expiry_time} นาที) -> ไม่ได้ยิงออเดอร์ (Mode: {mode})")

    @staticmethod
    def show_trade_result(won, symbol, order_id, pnl):
        status = 'ชนะ' if won else 'แพ้'
        if pnl == 0:
            status = 'เสมอ'
        thai_console_log(f"{status} {symbol} (ID: {order_id}) | PnL: {pnl:.2f}")

    @staticmethod
    def show_prices_and_balance(prices_dict, balance, pipeline_results: Optional[Dict[str, dict]] = None):
        try:
            price_parts = []
            for sym, price in prices_dict.items():
                extra = ""
                if pipeline_results and sym in pipeline_results:
                    res = pipeline_results[sym]
                    act = res.get("action", "HOLD")
                    conf = res.get("confidence", 0)
                    if act in ("CALL", "PUT"):
                        extra = f"->{act}({conf}%)"
                price_parts.append(f"{sym}:{price:.5f}{extra}")
            price_str = "] [".join(price_parts)
            balance_str = f"${balance:.2f}" if balance is not None else "N/A"
            thai_console_log(f"[{price_str}] :: TOTAL={balance_str}")
        except Exception as e:
            # Log error to file and continue with basic output
            logging.getLogger("FINALBOT").error(f"Error in show_prices_and_balance: {e}")
            # Zero Tolerance: must show price information
            raise RuntimeError(f"Price display failed: {e}")

    @staticmethod
    def show_stopping():
        thai_console_log("Stopping bot...")

    @staticmethod
    def show_payload_export(ready: list, failed: list):
        if failed:
            thai_console_log(f"[ Payload Export: {len(ready)}/{len(ready)+len(failed)} | Failed: {', '.join(failed)} ]")
        else:
            thai_console_log(f"[Bot Evaluate Market Complete {len(ready)} asset]")

    @staticmethod
    def show_ai_analysis_complete(decisions_or_count):
        try:
            if isinstance(decisions_or_count, dict):
                parts = []
                for sym, dec in decisions_or_count.items():
                    if isinstance(dec, dict):
                        act = str(dec.get("action", "WAIT")).upper().strip()
                        conf = int(round(float(dec.get("confidence_score", dec.get("confidence", 0)))))
                    else:
                        act = "WAIT"
                        conf = 0
                    parts.append(f"[{sym}:{act}({conf}%)]")
                sym_str = " ".join(parts)
                thai_console_log(f"[AI Analysis] {sym_str}" if sym_str else "[AI Analysis]")
            elif isinstance(decisions_or_count, list):
                parts = []
                for dec in decisions_or_count:
                    if isinstance(dec, dict):
                        sym = dec.get("symbol", "")
                        act = str(dec.get("action", "WAIT")).upper().strip()
                        conf = int(round(float(dec.get("confidence_score", dec.get("confidence", 0)))))
                    else:
                        sym = str(dec)
                        act = "WAIT"
                        conf = 0
                    parts.append(f"[{sym}:{act}({conf}%)]")
                sym_str = " ".join(parts)
                thai_console_log(f"[AI Analysis] {sym_str}" if sym_str else "[AI Analysis]")
            else:
                thai_console_log(f"[AI Analysis And Decisions Complete {decisions_or_count} Signal]")
        except Exception as e:
            thai_console_log(f"[AI Analysis Complete {decisions_or_count}]")

    @staticmethod
    def show_order_placed(payload_id: str, action: str, expiry_minutes: int, stake: float, order_id: Any):
        thai_console_log(f"[{payload_id}:{action}:{expiry_minutes}นาที:{int(stake)}THB] [ID:{order_id}]")

    @staticmethod
    def show_trade_settled(payload_id: str, action: str, expiry_minutes: int, stake: float, order_id: Any, result_status: str, profit_amount: float, balance: Any):
        if profit_amount > 0:
            profit_sign = f"+{profit_amount:.2f}"
        elif profit_amount < 0:
            profit_sign = f"{profit_amount:.2f}"
        else:
            profit_sign = "0.00"

        if balance is None:
            balance_formatted = "0THB"
        elif isinstance(balance, (int, float)):
            if float(balance).is_integer():
                balance_formatted = f"{int(balance):,}THB"
            else:
                balance_formatted = f"{balance:,.2f}THB"
        elif isinstance(balance, str):
            clean_b = balance.strip().replace("THB", "").replace(",", "").strip()
            try:
                val = float(clean_b)
                if val.is_integer():
                    balance_formatted = f"{int(val):,}THB"
                else:
                    balance_formatted = f"{val:,.2f}THB"
            except ValueError:
                balance_formatted = f"{balance.strip()}THB" if not balance.strip().endswith("THB") else balance.strip()
        else:
            balance_formatted = f"{balance}THB"

        msg = f"[{payload_id}:{action}:{expiry_minutes}นาที:{int(stake)}THB] [ID:{order_id}] [{result_status}:{profit_sign}THB::{balance_formatted}]"
        thai_console_log(msg)


@dataclass
class StrategyStats:
    """Statistics for a single strategy."""
    name: str
    version: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    trades_by_symbol: Dict[str, int] = field(default_factory=dict)
    pnl_by_symbol: Dict[str, float] = field(default_factory=dict)
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0
        return self.wins / self.total_trades
    
    @property
    def pnl_per_trade(self) -> float:
        if self.total_trades == 0:
            return 0
        return self.total_pnl / self.total_trades


class AdvancedDashboard:
    """
    Compare multiple strategies and analyze performance.
    """
    
    def __init__(self):
        """Initialize dashboard."""
        self.strategies: Dict[str, StrategyStats] = {}
        self.correlation_data: Dict[str, List[float]] = {}
        self.ml_metrics: Dict[str, float] = {}
    
    def register_strategy(self, name: str, version: str):
        """Register strategy for tracking."""
        key = f"{name}_v{version}"
        self.strategies[key] = StrategyStats(name=name, version=version)
        logger.info(f" Strategy registered: {key}")
    
    def record_trade(self, strategy_key: str, symbol: str, result: str, pnl: float):
        """Record trade result."""
        if strategy_key not in self.strategies:
            return
        
        stats = self.strategies[strategy_key]
        stats.total_trades += 1
        
        if result == "WIN":
            stats.wins += 1
        else:
            stats.losses += 1
        
        stats.total_pnl += pnl
        
        # Track by symbol
        if symbol not in stats.trades_by_symbol:
            stats.trades_by_symbol[symbol] = 0
            stats.pnl_by_symbol[symbol] = 0
        
        stats.trades_by_symbol[symbol] += 1
        stats.pnl_by_symbol[symbol] += pnl
    
    def get_strategy_comparison(self) -> Dict:
        """Compare all strategies."""
        comparison = {}
        
        for key, stats in self.strategies.items():
            comparison[key] = {
                'name': stats.name,
                'version': stats.version,
                'total_trades': stats.total_trades,
                'win_rate': f"{stats.win_rate * 100:.1f}%",
                'total_pnl': f"{stats.total_pnl:.2f}",
                'pnl_per_trade': f"{stats.pnl_per_trade:.2f}",
                'symbol_performance': stats.pnl_by_symbol,
            }
        
        return comparison
    
    def get_symbol_performance(self) -> Dict[str, Dict]:
        """Get performance by symbol across all strategies."""
        symbols_perf = {}
        
        for strat_key, stats in self.strategies.items():
            for symbol, pnl in stats.pnl_by_symbol.items():
                if symbol not in symbols_perf:
                    symbols_perf[symbol] = {
                        'total_pnl': 0,
                        'strategy_count': 0,
                    }
                
                symbols_perf[symbol]['total_pnl'] += pnl
                symbols_perf[symbol]['strategy_count'] += 1
        
        return symbols_perf
    
    def record_ml_metric(self, metric_name: str, value: float):
        """Record ML optimization metric."""
        self.ml_metrics[metric_name] = value
        logger.info(f" ML Metric: {metric_name} = {value:.3f}")
    
    def generate_report(self) -> str:
        """Generate summary report."""
        report = f"\n{'='*60}\n"
        report += " ADVANCED ANALYTICS DASHBOARD\n"
        report += f"{'='*60}\n\n"
        
        # Strategy comparison
        report += " STRATEGY COMPARISON\n"
        report += f"{'-'*60}\n"
        for key, stats in self.strategies.items():
            report += f"{key}:\n"
            report += f"  Trades: {stats.total_trades} | WR: {stats.win_rate*100:.1f}%\n"
            report += f"  P&L: {stats.total_pnl:.2f} | Per Trade: {stats.pnl_per_trade:.2f}\n"
        
        # Symbol performance
        report += f"\n{'='*60}\n"
        report += " SYMBOL PERFORMANCE\n"
        report += f"{'-'*60}\n"
        perf = self.get_symbol_performance()
        for symbol, data in perf.items():
            report += f"{symbol}: P&L={data['total_pnl']:.2f} ({data['strategy_count']} strategies)\n"
        
        # ML metrics
        report += f"\n{'='*60}\n"
        report += " ML OPTIMIZATION METRICS\n"
        report += f"{'-'*60}\n"
        for metric, value in self.ml_metrics.items():
            report += f"{metric}: {value:.3f}\n"
        
        report += f"{'='*60}\n"
        return report
