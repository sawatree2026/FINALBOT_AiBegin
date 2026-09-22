"""
Order Tracker & Trade History Logger for Part 3
===============================================
Asynchronously monitors active binary option orders until expiration,
determines settlement results (WIN/LOSE/EQUAL), notifies MoneyManager,
and logs all trades to `data_base/trades/trades_history.csv`.
"""

import os
import csv
import time
import logging
import threading
import traceback
import concurrent.futures
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from data_trade.execution_gate.broker_executor import resolve_api

logger = logging.getLogger("OrderTracker")

CSV_HEADER = [
    "timestamp",
    "order_id",
    "symbol",
    "action",
    "stake",
    "expiry_minutes",
    "result",
    "profit_amount",
    "confidence_score",
    "ai_engine",
    "reason_th",
]


class OrderTracker:
    """Tracks order lifecycle and persists historical trade logs."""

    def __init__(self, money_manager: Optional[Any] = None):
        self.money_manager = money_manager
        self.history_dir = os.path.join("logs", "logs_data_trade")
        self.history_file = os.path.join(self.history_dir, "trades_history.csv")
        self._ensure_csv_file()
        
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=10,
            thread_name_prefix="OrderTracker"
        )
        self._lock = threading.Lock()

    def _ensure_csv_file(self) -> None:
        """Creates the history directory and CSV file with header if missing."""
        os.makedirs(self.history_dir, exist_ok=True)
        if not os.path.exists(self.history_file):
            with open(self.history_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADER)

    def track_order(
        self,
        order_data: Dict[str, Any],
        ai_decision: Dict[str, Any],
        broker_adapter: Any
    ) -> None:
        """
        Enqueues order for asynchronous monitoring and settlement logging.
        
        Args:
            order_data: Order placement response from BrokerExecutor.
            ai_decision: Decision dict from AIDispatcher.
            broker_adapter: Broker connection facade.
        """
        order_id = order_data.get("order_id")
        if not order_id:
            logger.warning("[OrderTracker] Cannot track order without valid order_id")
            return

        if self.money_manager:
            self.money_manager.register_open_trade(order_id=order_id, symbol=order_data.get("symbol", ""))

        self.executor.submit(
            self._monitor_order_lifecycle,
            order_data=order_data,
            ai_decision=ai_decision,
            broker_adapter=broker_adapter
        )

    def _monitor_order_lifecycle(
        self,
        order_data: Dict[str, Any],
        ai_decision: Dict[str, Any],
        broker_adapter: Any
    ) -> None:
        """Background worker tracking expiration and recording win/loss."""
        order_id = order_data.get("order_id")
        symbol = order_data.get("symbol", "UNKNOWN")
        action = order_data.get("action", "UNKNOWN")
        stake = float(order_data.get("stake", 0.0))
        expiry_minutes = int(order_data.get("expiry_minutes", 1))
        confidence_score = ai_decision.get("confidence_score", 0)
        ai_engine = ai_decision.get("engine_used", "UNKNOWN")
        reason_th = ai_decision.get("reason_th", "")
        payload_id = (
            ai_decision.get("ID")
            or ai_decision.get("payload_id")
            or ai_decision.get("id")
            or order_data.get("payload_id")
            or symbol
        )

        api = resolve_api(broker_adapter)
        wait_seconds = max(5, expiry_minutes * 60 + 5)
        logger.info(f"[OrderTracker] Monitoring Order {order_id} ({symbol} {action} {expiry_minutes}m) - waiting {wait_seconds}s for expiry...")

        # Sleep until expiration
        time.sleep(wait_seconds)

        result_status = "UNKNOWN"
        profit_amount = 0.0

        try:
            # Poll check_win from broker API
            if api and hasattr(api, "check_win_v3"):
                for attempt in range(6):
                    try:
                        win_res, net_profit = api.check_win_v3(int(order_id) if order_id.isdigit() else order_id)
                        if win_res is not None:
                            if win_res == "win":
                                result_status = "WIN"
                                profit_amount = float(net_profit) if net_profit is not None else stake * 0.85
                            elif win_res == "loose" or win_res == "lose":
                                result_status = "LOSE"
                                profit_amount = -stake
                            elif win_res == "equal":
                                result_status = "EQUAL"
                                profit_amount = 0.0
                            break
                    except Exception as pe:
                        logger.warning(f"[OrderTracker] Check win attempt {attempt+1} failed for {order_id}: {pe}")
                    time.sleep(3)

            # Fallback if result status not obtained
            if result_status == "UNKNOWN":
                logger.warning(f"[OrderTracker] Could not resolve win status for {order_id} from API — defaulting to EQUAL")
                result_status = "EQUAL"
                profit_amount = 0.0

        except Exception as e:
            logger.exception(f"[OrderTracker] Error settling order {order_id}: {e}")
            traceback.print_exc()

        # Update MoneyManager
        if self.money_manager:
            try:
                self.money_manager.record_trade_result(
                    order_id=order_id,
                    profit_amount=profit_amount,
                    result_status=result_status
                )
            except Exception as me:
                logger.exception(f"[OrderTracker] Error notifying MoneyManager: {me}")

        # Retrieve latest balance
        balance = None
        if broker_adapter is not None:
            try:
                if hasattr(broker_adapter, "get_balance"):
                    balance = float(broker_adapter.get_balance())
                elif hasattr(broker_adapter, "api") and hasattr(broker_adapter.api, "get_balance"):
                    balance = float(broker_adapter.api.get_balance())
            except Exception as be:
                logger.warning(f"[OrderTracker] Could not retrieve balance from broker_adapter: {be}")

        if balance is None and self.money_manager is not None:
            try:
                if hasattr(self.money_manager, "current_balance"):
                    balance = float(self.money_manager.current_balance)
                elif hasattr(self.money_manager, "balance"):
                    balance = float(self.money_manager.balance)
            except Exception:
                pass

        # Show Trade Settled on Console UI
        try:
            from monitoring.console_dashboard import ConsoleUI
            ConsoleUI.show_trade_settled(
                payload_id=payload_id,
                action=action,
                expiry_minutes=expiry_minutes,
                stake=stake,
                order_id=order_id,
                result_status=result_status,
                profit_amount=profit_amount,
                balance=balance
            )
        except Exception as cue:
            logger.warning(f"[OrderTracker] Failed to display trade settlement on console: {cue}")

        # Append to CSV
        tz_thailand = timezone(timedelta(hours=7))
        record_timestamp = datetime.now(tz_thailand).isoformat()

        row = [
            record_timestamp,
            order_id,
            symbol,
            action,
            f"{stake:.2f}",
            expiry_minutes,
            result_status,
            f"{profit_amount:+.2f}",
            confidence_score,
            ai_engine,
            reason_th,
        ]

        with self._lock:
            try:
                with open(self.history_file, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
                logger.info(
                    f"[OrderTracker] Trade Settled & Saved -> ID: {order_id}, "
                    f"Symbol: {symbol}, Result: {result_status}, PnL: {profit_amount:+.2f} THB"
                )
            except Exception as fe:
                logger.exception(f"[OrderTracker] Failed to write trade history to CSV: {fe}")
