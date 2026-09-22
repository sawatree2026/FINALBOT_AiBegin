"""
Order Tracker & Trade History Logger for Part 3 / Part 4
========================================================
Asynchronously monitors active binary option orders until expiration,
determines settlement results (WIN/LOSE/EQUAL), notifies MoneyManager,
and logs all trades to dedicated per-symbol file:
`data_base/trade_result/<SYMBOL>.csv`
and Master history CSV:
`data_base/trade_result/trades_history.csv`
"""

import os
import csv
import time
import logging
import threading
import traceback
import concurrent.futures
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from data_trade.execution_gate.broker_executor import resolve_api

logger = logging.getLogger("OrderTracker")


class OrderTracker:
    """Tracks order lifecycle and persists historical trade logs."""

    def __init__(self, money_manager: Optional[Any] = None):
        self.money_manager = money_manager
        self.history_dir = os.path.join("data_base", "trade_result")
        self.history_file = os.path.join(self.history_dir, "trades_history.csv")
        self._ensure_csv_file(self.history_file)
        
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=10,
            thread_name_prefix="OrderTracker"
        )
        self._lock = threading.Lock()

    def _ensure_csv_file(self, file_path: str) -> None:
        """Creates parent directory if missing."""
        dir_path = os.path.dirname(file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

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
        expiry_minutes = int(order_data.get("expiry_minutes", 5))
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
            if api is None or not hasattr(api, "check_win_v3"):
                raise RuntimeError("broker API does not implement check_win_v3")

            for attempt in range(6):
                try:
                    win_res, net_profit = api.check_win_v3(int(order_id) if order_id.isdigit() else order_id)
                    if win_res is not None:
                        if win_res == "win":
                            result_status = "WIN"
                            if net_profit is None:
                                raise RuntimeError("broker returned WIN without net profit")
                            profit_amount = float(net_profit)
                        elif win_res in ("loose", "lose"):
                            result_status = "LOSE"
                            profit_amount = -stake
                        elif win_res == "equal":
                            result_status = "EQUAL"
                            profit_amount = 0.0
                        else:
                            raise RuntimeError(f"unknown settlement status: {win_res!r}")
                        break
                except Exception as pe:
                    logger.exception(
                        f"[OrderTracker] Check win attempt {attempt + 1} failed for {order_id}: {pe}"
                    )
                    if attempt == 5:
                        raise
                time.sleep(3)

            if result_status == "UNKNOWN":
                raise RuntimeError(
                    f"FAIL-FAST: Could not resolve settlement for order {order_id}"
                )

        except Exception as e:
            logger.exception(f"[OrderTracker] Error settling order {order_id}: {e}")
            traceback.print_exc()
            logging.shutdown()
            os._exit(1)

        # Update MoneyManager
        if self.money_manager:
            self.money_manager.record_trade_result(
                order_id=order_id,
                profit_amount=profit_amount,
                result_status=result_status
            )

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

        # Save to CSV
        self._save_trade_record(
            symbol=str(symbol),
            payload_id=str(payload_id),
            order_id=str(order_id),
            action=str(action),
            expiry_minutes=int(expiry_minutes),
            stake=float(stake),
            result_status=str(result_status),
            profit_amount=float(profit_amount),
            balance=balance
        )

    def _save_trade_record(
        self,
        symbol: str,
        payload_id: str,
        order_id: str,
        action: str,
        expiry_minutes: int,
        stake: float,
        result_status: str,
        profit_amount: float,
        balance: Optional[float] = None
    ) -> None:
        """Persists settled trade record to dedicated per-symbol CSV and master CSV."""
        with self._lock:
            try:
                tz_thailand = timezone(timedelta(hours=7))
                now_str = datetime.now(tz_thailand).strftime("%Y-%m-%d %H:%M:%S")
                balance_str = f"{float(balance):.2f}$" if balance is not None else "0.00$"
                formatted_line = f"{now_str}, [{payload_id}]:[{order_id}]:[{symbol}]:[{action}]:[{expiry_minutes}m]:[{stake:.2f}]:[{result_status}]:[{profit_amount:+.2f}]:[{balance_str}]"

                # 1. Per-symbol dedicated CSV: data_base/trade_result/<SYMBOL>.csv
                if symbol and symbol != "UNKNOWN":
                    symbol_file = os.path.join(self.history_dir, f"{symbol}.csv")
                    self._ensure_csv_file(symbol_file)
                    with open(symbol_file, "a", encoding="utf-8") as sf:
                        sf.write(formatted_line + "\n")

                # 2. Master CSV combining all symbols: data_base/trade_result/trades_history.csv
                self._ensure_csv_file(self.history_file)
                with open(self.history_file, "a", encoding="utf-8") as f:
                    f.write(formatted_line + "\n")

                logger.info(
                    f"[OrderTracker] Trade Settled & Saved -> {formatted_line}"
                )
            except Exception as fe:
                logger.exception(f"[OrderTracker] Failed to write trade history to CSV: {fe}")
