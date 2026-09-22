"""
IQ Option Data Feed Adapter (Facade / Coordinator)

Provides a unified interface conforming to IDataSource by coordinating
IQConnectionManager, IQRestFetcher, and IQStreamManager.
"""

import logging
from typing import Dict, List, Optional, Any
import pandas as pd

from data_feed.bridge_adapter.abstract_class import IDataSource
from .connection import IQConnectionManager
from .rest_fetcher import IQRestFetcher
from .stream_manager import IQStreamManager

logger = logging.getLogger(__name__)


class IQOptionAdapter(IDataSource):
    """
    IQ Option Adapter coordinating connection, REST fetcher, and stream manager.
    Conforms to IDataSource interface.
    """

    def __init__(self, email: Optional[str] = None,
                 password: Optional[str] = None,
                 account_type: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        Initialize IQ Option adapter facade.
        """
        self.connection_manager = IQConnectionManager(
            email=email,
            password=password,
            account_type=account_type,
            config=config
        )
        self.rest_fetcher = IQRestFetcher(
            timeout_sec=self.connection_manager.timeout_sec,
            max_workers=self.connection_manager.max_workers
        )
        self.stream_manager = IQStreamManager(
            timeout_sec=self.connection_manager.timeout_sec
        )
        logger.info("[IQOPTION] IQOptionAdapter facade initialized successfully")

    @property
    def connected(self) -> bool:
        """Returns True if the adapter is connected to the broker."""
        return self.connection_manager.connected

    @property
    def api(self) -> Any:
        """Access underlying API instance."""
        return self.connection_manager.api

    def is_connected(self) -> bool:
        """Check connection status."""
        return self.connection_manager.is_connected()

    def ensure_connected(self) -> None:
        """Reconnect check if the websocket dropped."""
        self.connection_manager.ensure_connected()

    def connect(self) -> None:
        """Connect to broker."""
        self.connection_manager.connect()

    def disconnect(self) -> None:
        """Disconnect from broker."""
        self.connection_manager.disconnect()

    def get_balance(self) -> float:
        """Get account balance."""
        return self.connection_manager.get_balance()

    def get_server_timestamp(self) -> float:
        """Get broker server timestamp."""
        return self.connection_manager.get_server_timestamp()

    def get_candles(self, symbol: str, timeframe: str = 'M1',
                    count: int = 250, end_time: Optional[Any] = None) -> pd.DataFrame:
        """
        Fetch historical candles via REST API.
        """
        self.ensure_connected()
        return self.rest_fetcher.fetch_candles(
            api=self.connection_manager.api,
            symbol=symbol,
            timeframe=timeframe,
            count=count,
            end_time=end_time
        )

    def get_multi_timeframe(self, symbol: str,
                            timeframes: Optional[List[str]] = None,
                            count: int = 250) -> Dict[str, pd.DataFrame]:
        """
        Fetch candles for multiple timeframes sequentially.
        """
        if timeframes is None:
            timeframes = ['M1', 'M5']
        
        result: Dict[str, pd.DataFrame] = {}
        for tf in timeframes:
            result[tf] = self.get_candles(symbol, timeframe=tf, count=count)
        return result

    def start_stream(self, symbol: str, timeframe: str = 'M1', count: int = 250) -> None:
        """
        Start WebSocket candle streaming.
        """
        self.ensure_connected()
        self.stream_manager.start_stream(
            api=self.connection_manager.api,
            symbol=symbol,
            timeframe=timeframe,
            count=count
        )

    def update_with_streaming(self, symbol: str, timeframe: str = 'M1', count: int = 250) -> pd.DataFrame:
        """
        Get latest candles from WebSocket cache.
        """
        self.ensure_connected()
        return self.stream_manager.update_with_streaming(
            api=self.connection_manager.api,
            symbol=symbol,
            timeframe=timeframe,
            count=count
        )

    def get_symbols(self) -> List[str]:
        """Get list of active trading symbols from configuration."""
        from config_setting.config_loader import get_symbols
        return get_symbols()

    def get_open_symbols(self, target_symbols: Optional[List[str]] = None) -> List[str]:
        """
        Return list of configured symbols to be verified directly against candle data.
        """
        return target_symbols if target_symbols is not None else self.get_symbols()
