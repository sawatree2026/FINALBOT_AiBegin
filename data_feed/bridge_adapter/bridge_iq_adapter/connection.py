"""
IQ Option Connection Manager

Handles authentication, broker connection state, account type switching (DEMO/REAL),
and balance/server timestamp operations with Zero Tolerance compliance.
"""

import logging
import threading
import time
import traceback
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class IQConnectionManager:
    """Manages connection lifecycle and account details for IQ Option."""

    def __init__(self, email: Optional[str] = None,
                 password: Optional[str] = None,
                 account_type: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        Initialize IQ Option connection manager.
        """
        if config is None:
            from config_setting.config_loader import load_datafeed_settings
            config = load_datafeed_settings()

        iq_config = config.get("data_feed", {}).get("iq_option_adapter", {})
        
        # Priority: explicit args > config_loader credentials
        if email and password:
            self.email = str(email)
            self.password = str(password)
        else:
            from config_setting.config_loader import get_iq_credentials
            self.email, self.password = get_iq_credentials()

        if account_type:
            self.account_type = str(account_type)
        else:
            from config_setting.config_loader import get_account_type
            self.account_type = get_account_type()

        self.timeout_sec: int = int(iq_config.get("timeout_sec", 8))
        self.max_workers: int = int(iq_config.get("max_workers", 10))

        # Zero Tolerance compliance check
        connection_retries = iq_config.get("connection_retries", 0)
        if connection_retries > 0:
            logger.error(f"[IQOPTION] Zero Tolerance VIOLATION: connection_retries={connection_retries}")
            raise RuntimeError("Zero Tolerance: connection retries not allowed")

        self.connection_retries: int = 0
        logger.info("[IQOPTION] ConnectionManager initialized with Zero Tolerance compliance")

        if not self.email or not self.password:
            raise RuntimeError(
                "IQ Option credentials missing. Provide email/password "
                "as arguments or configure in config/settings."
            )

        self._connected: bool = False
        self._conn_lock: threading.Lock = threading.Lock()
        self.api = None

        # Execute initial connection
        self._init_api()

    def _init_api(self) -> None:
        """Initialize and authenticate with IQ Option API."""
        try:
            from iqoptionapi.stable_api import IQ_Option
            self.IQ_Option = IQ_Option
            logger.info("Using stable_api.IQ_Option class")
        except ImportError as e:
            logger.exception("iqoptionapi library structure issue")
            raise RuntimeError(f"Cannot import IQ_Option: {e}") from e

        logger.info(f"[CONN] Connecting to IQ Option ({self.account_type}) as {self.email}...")
        self.api = self.IQ_Option(self.email, self.password)
        logger.info("[CONN] API created, attempting to connect...")
        
        ok, reason = self.api.connect()
        if not ok:
            raise RuntimeError(f"IQ Option login failed: {reason}")

        balance_mode = "PRACTICE" if str(self.account_type).upper() in ["DEMO", "PRACTICE"] else "REAL"
        self.api.change_balance(balance_mode)

        self._connected = True
        mode = "DEMO" if str(self.account_type).upper() in ["DEMO", "PRACTICE"] else "REAL MONEY"
        logger.info(f"[CONN] IQ Option connected ({mode})")

    @property
    def connected(self) -> bool:
        """Returns True if the adapter is connected to the broker."""
        return self._connected

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected

    def ensure_connected(self) -> None:
        """Reconnect check if the websocket dropped (called before fetch)."""
        if not self.api:
            raise RuntimeError("API not initialized")
        
        # Double-checked locking pattern for thread safety
        if not self.api.check_connect():
            with self._conn_lock:
                if not self.api.check_connect():
                    logger.error("[ERROR] IQ Option connection lost — Zero Tolerance: stopping immediately")
                    raise RuntimeError("IQ Option connection lost — no retry allowed")

    def connect(self) -> None:
        """Connect method for interface compliance."""
        if not self.connected:
            logger.warning("Connect called, re-initializing connection...")
            self._init_api()

    def disconnect(self) -> None:
        """Disconnect method for IQ Option adapter."""
        if self.api is not None:
            try:
                if hasattr(self.api, 'disconnect'):
                    self.api.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
        self._connected = False
        logger.info("[CONN] IQ Option disconnected")

    def get_balance(self) -> float:
        """Get account balance."""
        if not self._connected or self.api is None:
            raise RuntimeError("IQ Option not connected")
        try:
            balance_info = self.api.get_balance()
            if isinstance(balance_info, (int, float)):
                return float(balance_info)
            elif isinstance(balance_info, dict):
                return float(balance_info.get('balance', 0.0))
            return float(balance_info)
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise RuntimeError(f"Failed to get balance: {e}") from e

    def get_server_timestamp(self) -> float:
        """Get server timestamp from broker API with Fail-Fast compliance."""
        if not self._connected or self.api is None:
            raise RuntimeError("IQ Option not connected")
        try:
            server_ts = self.api.get_server_timestamp()
            if server_ts is not None:
                return float(server_ts)
            raise ValueError("api.get_server_timestamp() returned None")
        except Exception as e:
            logger.exception(f"Failed to get server timestamp: {e}")
            raise RuntimeError(f"FAIL-FAST: Failed to get server timestamp: {e}") from e
