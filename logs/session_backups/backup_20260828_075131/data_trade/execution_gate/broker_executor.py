"""
Broker Executor for Part 3 (Schema 2.0 Multi-Protocol Engine)
============================================================
Directs order placement to IQ Option with support for:
1. Binary / Turbo Options (Standard & OTC)
2. Digital Options Schema 2.0 (Dynamic Strike & Underlying Resolution)
3. Auto-Failover & Detailed Error Telemetry
"""

import time
import logging
import traceback
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("BrokerExecutor")


def resolve_api(broker_or_adapter: Any) -> Any:
    """
    Extracts underlying iqoptionapi instance from adapter wrapper.
    Shared utility for BrokerExecutor and OrderTracker.
    """
    if hasattr(broker_or_adapter, "api"):
        return broker_or_adapter.api
    if hasattr(broker_or_adapter, "broker_adapter") and hasattr(broker_or_adapter.broker_adapter, "api"):
        return broker_or_adapter.broker_adapter.api
    if hasattr(broker_or_adapter, "data_adapter") and hasattr(broker_or_adapter.data_adapter, "api"):
        return broker_or_adapter.data_adapter.api
    return broker_or_adapter


class BrokerExecutor:
    """Executes Binary & Digital Option orders against the broker connection (Schema 2.0)."""

    def __init__(self):
        pass

    def _ensure_symbol_registered(self, api: Any, symbol: str) -> None:
        """Dynamically registers symbol into OP_code.ACTIVES if missing."""
        try:
            import iqoptionapi.constants as OP_code
            if symbol not in OP_code.ACTIVES:
                init_data = api.get_all_init() if hasattr(api, "get_all_init") else {}
                for cat in ["turbo", "binary"]:
                    for aid, ainfo in init_data.get("result", {}).get(cat, {}).get("actives", {}).items():
                        name = ainfo.get("name", "").replace("front.", "")
                        if name:
                            OP_code.ACTIVES[name] = int(aid)
        except Exception as e:
            logger.warning(f"[BrokerExecutor] Could not dynamically register symbol {symbol}: {e}")

    def execute_order(
        self,
        symbol: str,
        action: str,
        expiry_minutes: int,
        stake: float,
        broker_adapter: Any
    ) -> Dict[str, Any]:
        """
        Submits option order to broker using Schema 2.0 Multi-Protocol Routing.
        
        Args:
            symbol: Asset symbol (e.g. 'EURUSD', 'GBPUSD', 'EURUSD-OTC', 'DIA', 'SPY').
            action: 'CALL' or 'PUT'.
            expiry_minutes: Contract expiration duration in minutes (1-5).
            stake: Order amount (e.g. 35.0).
            broker_adapter: Broker facade instance.
            
        Returns:
            Execution result dict with status, order_id, symbol, action, stake, expiry_minutes, timestamp, error, protocol.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("FAIL-FAST: symbol must be a valid non-empty string")

        norm_action = action.strip().upper()
        if norm_action not in ("CALL", "PUT"):
            raise ValueError(f"FAIL-FAST: Invalid action '{action}', must be 'CALL' or 'PUT'")

        if not (1 <= expiry_minutes <= 5):
            raise ValueError(f"FAIL-FAST: Invalid expiry_minutes '{expiry_minutes}', must be between 1 and 5")

        if not isinstance(stake, (int, float)) or stake <= 0:
            raise ValueError(f"FAIL-FAST: Invalid stake '{stake}', must be a positive number")

        api = resolve_api(broker_adapter)
        if api is None or not hasattr(api, "buy"):
            raise RuntimeError("FAIL-FAST: Broker API object does not implement .buy() method")

        # Ensure connection before ordering
        if hasattr(broker_adapter, "ensure_connected"):
            try:
                broker_adapter.ensure_connected()
            except Exception as e:
                logger.exception(f"[BrokerExecutor] Failed ensure_connected check: {e}")
                raise

        self._ensure_symbol_registered(api, symbol)

        tz_thailand = timezone(timedelta(hours=7))
        order_timestamp = datetime.now(tz_thailand).isoformat()
        act_param = "call" if norm_action == "CALL" else "put"

        logger.info(
            f"[BrokerExecutor] [Schema 2.0] Dispatching Order -> Symbol: {symbol}, Action: {norm_action}, "
            f"Expiry: {expiry_minutes}m, Stake: {stake:.2f} THB"
        )

        # ── Step 1: Protocol 1 (Binary / Turbo Standard Route) with Retry ─────
        start_t = time.time()
        last_error = None
        max_retries = 3
        
        for attempt in range(1, max_retries + 1):
            try:
                status, result_id = api.buy(
                    float(stake),
                    str(symbol),
                    str(act_param),
                    int(expiry_minutes)
                )
                elapsed = round(time.time() - start_t, 3)

                if status and result_id is not None:
                    order_id_str = str(result_id)
                    logger.info(
                        f"[BrokerExecutor] Order Placed SUCCESS (Binary/Turbo) -> ID: {order_id_str}, "
                        f"Symbol: {symbol}, Action: {norm_action}, Elapsed: {elapsed}s, Attempt: {attempt}"
                    )
                    return {
                        "status": "SUCCESS",
                        "order_id": order_id_str,
                        "symbol": symbol,
                        "action": norm_action,
                        "stake": float(stake),
                        "expiry_minutes": int(expiry_minutes),
                        "timestamp": order_timestamp,
                        "protocol": "BINARY_TURBO",
                        "error": None,
                        "latency_sec": elapsed,
                        "retry_attempt": attempt
                    }
                else:
                    last_error = str(result_id) if result_id is not None else "Unknown broker rejection"
                    logger.warning(
                        f"[BrokerExecutor] Binary/Turbo Route rejected (Attempt {attempt}/{max_retries}) -> "
                        f"Symbol: {symbol}, Action: {norm_action}, Reason: {last_error}"
                    )
                    
                    # ถ้ายังไม่ครบ retry次数 รอ 1 วินาทีแล้วลองใหม่
                    if attempt < max_retries:
                        logger.info(f"[BrokerExecutor] Retrying in 1 second...")
                        time.sleep(1.0)
                        continue
                    else:
                        # ครบ retry แล้วยังล้มเหลว
                        break

            except Exception as e:
                last_error = str(e)
                logger.exception(
                    f"[BrokerExecutor] Exception during order execution (Attempt {attempt}/{max_retries}) "
                    f"for {symbol}: {e}"
                )
                
                # ถ้ายังไม่ครบ retry次数 รอ 1 วินาทีแล้วลองใหม่
                if attempt < max_retries:
                    logger.info(f"[BrokerExecutor] Retrying in 1 second after exception...")
                    time.sleep(1.0)
                    continue
                else:
                    # ครบ retry แล้วยังล้มเหลว
                    traceback.print_exc()
                    raise RuntimeError(
                        f"FAIL-FAST: Broker order execution error for {symbol} after {max_retries} attempts: {last_error}"
                    ) from e
        
        # ถ้ามาที่นี่ = ครบ retry แล้วยัง FAILED (status=False)
        elapsed = round(time.time() - start_t, 3)
        error_reason = last_error or "Unknown broker rejection after retries"

        # ── Step 2: Protocol 2 (Digital Options V2 Fallback) ────────────
        if "not available" in error_reason or "suspended" in error_reason or "invalid" in error_reason:
            logger.info(f"[BrokerExecutor] [Schema 2.0] Attempting Digital Options V2 fallback for {symbol}...")
            digital_status, digital_id = self._try_digital_v2(api, symbol, act_param, stake, expiry_minutes)
            if digital_status and digital_id is not None:
                elapsed = round(time.time() - start_t, 3)
                logger.info(
                    f"[BrokerExecutor] Order Placed SUCCESS (Digital V2) -> ID: {digital_id}, "
                    f"Symbol: {symbol}, Action: {norm_action}, Elapsed: {elapsed}s"
                )
                return {
                    "status": "SUCCESS",
                    "order_id": str(digital_id),
                    "symbol": symbol,
                    "action": norm_action,
                    "stake": float(stake),
                    "expiry_minutes": int(expiry_minutes),
                    "timestamp": order_timestamp,
                    "protocol": "DIGITAL_V2",
                    "error": None,
                    "latency_sec": elapsed,
                    "retry_attempt": max_retries
                }

        return {
            "status": "FAILED",
            "order_id": None,
            "symbol": symbol,
            "action": norm_action,
            "stake": float(stake),
            "expiry_minutes": int(expiry_minutes),
            "timestamp": order_timestamp,
            "protocol": "BINARY_TURBO",
            "error": error_reason,
            "latency_sec": elapsed,
            "retry_attempt": max_retries
        }

    def _try_digital_v2(self, api: Any, symbol: str, action: str, stake: float, duration: int) -> tuple:
        """Helper to safely execute Digital Option V2 orders with strict timeout and no hanging."""
        import threading

        result = [False, None]

        def _worker():
            try:
                if hasattr(api, "buy_digital_spot"):
                    clean_sym = symbol.replace("-OTC", "").upper()
                    s, oid = api.buy_digital_spot(clean_sym, float(stake), action, int(duration))
                    if s and oid and (isinstance(oid, int) or str(oid).isdigit()):
                        result[0] = True
                        result[1] = str(oid)
            except Exception as e:
                logger.debug(f"[BrokerExecutor] Digital fallback worker error: {e}")

        th = threading.Thread(target=_worker, daemon=True)
        th.start()
        th.join(timeout=3.0)

        if result[0]:
            return True, result[1]
        return False, None
