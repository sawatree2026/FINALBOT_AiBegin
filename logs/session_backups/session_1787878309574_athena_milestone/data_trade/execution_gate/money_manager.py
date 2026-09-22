"""
Money Manager & Risk Control Engine for Part 3 / Part 4
======================================================
Manages position sizing (Fixed Stake), daily profit/loss limits (TP/SL),
daily trades limits, consecutive losses & cooldown, active order tracking
(no duplicate trades on same symbol), and account balance checks.
"""

import os
import csv
import logging
from typing import Dict, Any, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta

from config_setting.config_loader import load_settings

logger = logging.getLogger("MoneyManager")


class MoneyManager:
    """Calculates stake sizes and enforces strict capital preservation limits in Part 3 / Part 4."""

    DEFAULT_STAKE_PER_TRADE: float = 35.0
    DEFAULT_MAX_DAILY_PROFIT: float = 1000.0
    DEFAULT_MAX_DAILY_LOSS: float = 500.0
    DEFAULT_MAX_DAILY_TRADES: int = 20
    DEFAULT_MAX_CONSECUTIVE_LOSSES: int = 3
    DEFAULT_MAX_CONCURRENT_ORDERS: int = 3
    DEFAULT_COOLDOWN_MINUTES: int = 5

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.settings = config or load_settings(reload=False)
        acc_cfg = self.settings.get("account", {})
        
        # Native Risk Limits from config_setting/settings.json
        self.stake_per_trade: float = float(acc_cfg.get("stake_per_trade", self.DEFAULT_STAKE_PER_TRADE))
        self.max_daily_profit: float = float(acc_cfg.get("max_daily_profit", self.DEFAULT_MAX_DAILY_PROFIT))
        self.max_daily_loss: float = float(acc_cfg.get("max_daily_loss", self.DEFAULT_MAX_DAILY_LOSS))
        self.max_daily_trades: int = int(acc_cfg.get("max_daily_trades", self.DEFAULT_MAX_DAILY_TRADES))
        self.max_consecutive_losses: int = int(acc_cfg.get("max_consecutive_losses", self.DEFAULT_MAX_CONSECUTIVE_LOSSES))
        self.max_concurrent_orders: int = int(acc_cfg.get("max_concurrent_orders", acc_cfg.get("max_concurrent", self.DEFAULT_MAX_CONCURRENT_ORDERS)))
        self.cooldown_minutes: int = int(acc_cfg.get("cooldown_minutes", self.DEFAULT_COOLDOWN_MINUTES))

        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.consecutive_losses: int = 0
        self.active_symbols: Set[str] = set()
        self.active_orders: Dict[str, str] = {}  # {order_id: symbol}
        self.last_loss_time: Optional[datetime] = None
        self.trade_history_file: str = os.path.join("logs", "logs_data_trade", "trades_history.csv")

        self._load_today_history()

    def _load_today_history(self) -> None:
        """Parses today's trade records to initialize daily PnL, trade count, and loss counters."""
        if not os.path.exists(self.trade_history_file):
            return

        tz_thailand = timezone(timedelta(hours=7))
        today_str = datetime.now(tz_thailand).strftime("%Y-%m-%d")

        try:
            with open(self.trade_history_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                today_pnl = 0.0
                today_trades = 0
                consec_loss = 0
                last_loss = None

                for row in reader:
                    ts = row.get("timestamp", "")
                    if ts.startswith(today_str):
                        today_trades += 1
                        try:
                            profit = float(row.get("profit_amount", 0.0))
                            today_pnl += profit
                            res = str(row.get("result", "")).upper()
                            if res == "LOSE":
                                consec_loss += 1
                                parsed_dt = datetime.fromisoformat(ts)
                                if parsed_dt.tzinfo is None:
                                    parsed_dt = parsed_dt.replace(tzinfo=tz_thailand)
                                last_loss = parsed_dt
                            elif res == "WIN":
                                consec_loss = 0
                        except (ValueError, TypeError):
                            pass

                self.daily_pnl = today_pnl
                self.daily_trades = today_trades
                self.consecutive_losses = consec_loss
                self.last_loss_time = last_loss
                logger.info(
                    f"[MoneyManager] Synced today's history: PnL={self.daily_pnl:.2f}, "
                    f"DailyTrades={self.daily_trades}, ConsecLosses={self.consecutive_losses}"
                )
        except Exception as e:
            logger.warning(f"[MoneyManager] Could not parse trade history file: {e}")

    def can_trade(self, symbol: str = "", balance: float = 999999.0) -> Tuple[bool, str]:
        """
        Evaluates risk management constraints.
        
        Args:
            symbol: Asset symbol to check for active order duplicates.
            balance: Current broker account balance.
            
        Returns:
            Tuple[bool, str]: (is_allowed, reason_message)
        """
        # เงื่อนไขที่ 1: ห้ามยิงซ้ำคู่เงินเดียวกันขณะมีออเดอร์ทำงานอยู่
        if symbol and symbol in self.active_symbols:
            return False, f"คู่เงิน {symbol} กำลังมีออเดอร์ทำงานอยู่ (ห้ามยิงซ้ำในคู่เงินเดียวกันค่ะ)"

        # เงื่อนไขที่ 2: จำกัดจำนวนไม้พร้อมกันสูงสุด (Max Concurrent Orders)
        if len(self.active_orders) >= self.max_concurrent_orders:
            return False, f"จำนวนออเดอร์พร้อมกันเต็มโควตา ({len(self.active_orders)}/{self.max_concurrent_orders} ไม้)"

        # เงื่อนไขที่ 3: จำกัดจำนวนไม้เทรดสูงสุดต่อวัน (Max Daily Trades)
        total_trades = self.daily_trades + len(self.active_orders)
        if total_trades >= self.max_daily_trades:
            return False, f"จำนวนไม้เทรดวันนี้เต็มโควตาสูงสุดแล้ว ({total_trades}/{self.max_daily_trades} ไม้)"

        # เงื่อนไขที่ 4: ตรวจสอบการแพ้ติดต่อกันและช่วงพักการเทรด (Max Consecutive Losses & Cooldown)
        if self.consecutive_losses >= self.max_consecutive_losses:
            if self.cooldown_minutes > 0 and self.last_loss_time is not None:
                tz_thailand = timezone(timedelta(hours=7))
                now = datetime.now(tz_thailand)
                last_time = self.last_loss_time
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=tz_thailand)
                elapsed_seconds = (now - last_time).total_seconds()
                cooldown_seconds = self.cooldown_minutes * 60.0
                if elapsed_seconds < cooldown_seconds:
                    remaining_min = (cooldown_seconds - elapsed_seconds) / 60.0
                    return False, f"อยู่ในช่วงพักการเทรดหลังแพ้ติดกัน ({self.consecutive_losses}/{self.max_consecutive_losses} ครั้ง, เหลือเวลา Cooldown {remaining_min:.1f} นาที)"
            else:
                return False, f"แพ้ติดต่อกันเต็มโควตาสูงสุด ({self.consecutive_losses}/{self.max_consecutive_losses} ครั้ง)"

        # เงื่อนไขที่ 5: ตรวจ Stop Loss - SL รายวัน
        if self.daily_pnl <= -abs(self.max_daily_loss):
            return False, f"แตะขีดจำกัดขาดทุนรายวัน (SL) ({self.daily_pnl:.2f}/-{self.max_daily_loss:.2f} THB)"

        # เงื่อนไขที่ 6: ตรวจ Take Profit - TP รายวัน
        if self.daily_pnl >= abs(self.max_daily_profit):
            return False, f"แตะเป้าหมายกำไรรายวัน (TP) ({self.daily_pnl:.2f}/+{self.max_daily_profit:.2f} THB)"

        # เงื่อนไขที่ 7: ตรวจยอดเงิน Balance
        if balance < self.stake_per_trade:
            return False, f"ยอดเงินคงเหลือไม่เพียงพอ ({balance:.2f} < {self.stake_per_trade:.2f} THB)"

        return True, "RISK_GATES_PASSED"

    def get_stake(self, symbol: str = "") -> float:
        """Returns the configured fixed stake for the order."""
        return float(self.stake_per_trade)

    def register_open_trade(self, order_id: str, symbol: str) -> None:
        """Registers a newly opened order in active orders tracking."""
        order_str = str(order_id)
        self.active_orders[order_str] = symbol
        if symbol:
            self.active_symbols.add(symbol)
        logger.info(
            f"[MoneyManager] Registered open trade: ID={order_id}, Symbol={symbol}, "
            f"ActiveSymbols={list(self.active_symbols)}, TotalActive={len(self.active_orders)}"
        )

    def record_trade_result(self, order_id: str, profit_amount: float, result_status: str) -> None:
        """
        Updates internal risk metrics when an order finishes.
        
        Args:
            order_id: Order identifier.
            profit_amount: Net profit (positive) or loss (negative).
            result_status: 'WIN', 'LOSE', or 'EQUAL'.
        """
        order_str = str(order_id)
        sym = self.active_orders.pop(order_str, None)
        if sym:
            if not any(s == sym for s in self.active_orders.values()):
                self.active_symbols.discard(sym)

        self.daily_trades += 1
        self.daily_pnl += profit_amount
        norm_res = str(result_status).upper()

        if norm_res == "LOSE":
            self.consecutive_losses += 1
            tz_thailand = timezone(timedelta(hours=7))
            self.last_loss_time = datetime.now(tz_thailand)
        elif norm_res == "WIN":
            self.consecutive_losses = 0

        logger.info(
            f"[MoneyManager] Order {order_id} recorded: Result={norm_res}, "
            f"Profit={profit_amount:+.2f}, DailyPnL={self.daily_pnl:+.2f}, "
            f"DailyTrades={self.daily_trades}, ConsecLoss={self.consecutive_losses}, "
            f"RemainingActive={list(self.active_symbols)}"
        )

    def get_risk_status(self) -> Dict[str, Any]:
        """Returns current risk status summary."""
        return {
            "stake_per_trade": self.stake_per_trade,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "consecutive_losses": self.consecutive_losses,
            "active_symbols": list(self.active_symbols),
            "active_orders_count": len(self.active_orders),
            "max_concurrent_orders": self.max_concurrent_orders,
            "max_daily_trades": self.max_daily_trades,
            "max_daily_loss": self.max_daily_loss,
            "max_daily_profit": self.max_daily_profit,
            "max_consecutive_losses": self.max_consecutive_losses,
            "cooldown_minutes": self.cooldown_minutes,
            "last_loss_time": self.last_loss_time.isoformat() if self.last_loss_time else None,
        }
