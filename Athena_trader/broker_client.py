import time
import logging
import traceback
import pandas as pd
from typing import Optional, Tuple, List, Dict, Any
from iqoptionapi.stable_api import IQ_Option

logger = logging.getLogger("AthenaBroker")

class AthenaBrokerClient:
    def __init__(self, email: str, password: str, account_type: str = "DEMO"):
        self.email = email
        self.password = password
        self.account_type = account_type.upper()
        self.api: Optional[IQ_Option] = None
        self.connected = False

    def connect(self) -> bool:
        try:
            logger.info("Connecting to IQ Option...")
            self.api = IQ_Option(self.email, self.password)
            check, reason = self.api.connect()
            if not check:
                logger.error(f"Failed to connect IQ Option: {reason}")
                self.connected = False
                return False
            
            # Enforce Practice/Demo account
            balance_mode = "PRACTICE" if self.account_type in ["DEMO", "PRACTICE"] else "REAL"
            self.api.change_balance(balance_mode)
            
            # Dynamically register all active pairs (including -op real market pairs)
            try:
                from iqoptionapi.constants import ACTIVES
                all_init = self.api.get_all_init().get("result", {})
                for category in ["turbo", "binary"]:
                    actives = all_init.get(category, {}).get("actives", {})
                    for act_id, item in actives.items():
                        name = item.get("name", "").replace("front.", "")
                        if name:
                            ACTIVES[name] = int(act_id)
            except Exception as e:
                logger.warning(f"Failed to dynamically register actives: {e}")

            self.connected = True
            logger.info(f"Successfully connected to IQ Option! Balance mode: {balance_mode}")
            return True
        except Exception as e:
            logger.error(f"Exception during connection: {e}")
            traceback.print_exc()
            self.connected = False
            return False

    def get_balance(self) -> float:
        if not self.connected or not self.api:
            return 0.0
        try:
            return float(self.api.get_balance())
        except Exception:
            return 0.0

    def get_server_time(self) -> int:
        if not self.connected or not self.api:
            return int(time.time())
        try:
            return int(self.api.get_server_timestamp())
        except Exception:
            return int(time.time())

    def get_candles(self, symbol: str, timeframe_sec: int, count: int = 250) -> pd.DataFrame:
        if not self.connected or not self.api:
            raise RuntimeError("Broker is not connected")

        end_from_time = self.get_server_time()
        raw_candles = self.api.get_candles(symbol, timeframe_sec, count, end_from_time)
        
        if not raw_candles or not isinstance(raw_candles, list) or len(raw_candles) == 0:
            raise ValueError(f"No candle data returned for {symbol} (TF={timeframe_sec}s)")

        data = []
        for c in raw_candles:
            data.append({
                "timestamp": c.get("from", c.get("time", 0)),
                "open": float(c.get("open", 0.0)),
                "high": float(c.get("max", c.get("high", 0.0))),
                "low": float(c.get("min", c.get("low", 0.0))),
                "close": float(c.get("close", 0.0)),
                "volume": int(c.get("volume", 0))
            })

        df = pd.DataFrame(data)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df

    def execute_order(self, symbol: str, action: str, amount: float, duration: int) -> Tuple[bool, Optional[Any], str]:
        if not self.connected or not self.api:
            return False, None, "Broker is not connected"

        act = action.lower()
        if act not in ["call", "put"]:
            return False, None, f"Invalid action: {action}"

        try:
            # 1. Try Binary Option first
            check, order_id = self.api.buy(amount, symbol, act, duration)
            if check:
                return True, order_id, f"Binary order placed successfully (ID: {order_id})"
            
            # 2. If Binary Option unavailable or fails, try Digital Option
            logger.info("Binary option not available, trying Digital Option...")
            check_dig, order_id_dig = self.api.buy_digital_spot(symbol, amount, act, duration)
            if check_dig:
                return True, order_id_dig, f"Digital order placed successfully (ID: {order_id_dig})"

            return False, None, f"Order placement rejected by broker (Check={check}, Dig={check_dig})"
        except Exception as e:
            traceback.print_exc()
            return False, None, f"Order execution failed with exception: {e}"

    def check_trade_result(self, order_id: Any, is_digital: bool = False) -> Tuple[str, float]:
        if not self.connected or not self.api or not order_id:
            return "UNKNOWN", 0.0

        try:
            if is_digital:
                result = self.api.check_win_digital_v2(order_id)
                # result is profit or False
                if result is not False:
                    profit = float(result)
                    return ("WIN" if profit > 0 else "LOSS" if profit < 0 else "EQUAL"), profit
            else:
                result = self.api.check_win_v4(order_id)
                if result is not None:
                    status = result[0]
                    profit = float(result[1]) if len(result) > 1 else 0.0
                    return ("WIN" if profit > 0 else "LOSS" if profit < 0 else "EQUAL"), profit
        except Exception as e:
            logger.error(f"Error checking trade result: {e}")
            
        return "PENDING", 0.0

    def disconnect(self):
        if self.api:
            try:
                self.api = None
                self.connected = False
            except Exception:
                pass
