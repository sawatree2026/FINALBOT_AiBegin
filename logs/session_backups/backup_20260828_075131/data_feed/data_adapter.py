"""
Data Adapter - Market Ingestion Core (Coordinator)

หน้าที่: ประสานงานระหว่าง DataValidator, CandleProcessor, และ RAMCacheStore
ฟังก์ชัน: Mapping Field, Timestamp, Symbol, Timeframe, Type Conversion
"""

import concurrent.futures
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging
import threading
import time

from data_feed.bridge_adapter.abstract_class import IDataSource
from data_feed.csv_queue import CSVQueue
from data_feed.csv_manager import CSVManager
from data_feed.csv_writer import get_file_lock, read_csv_safe
from data_feed.exceptions import DataFeedError, DataGapError

# Import modular components
from data_feed.data_validator import DataValidator
from data_feed.data_processor import (
    drop_forming,
    merge_candles,
    add_age_and_quality,
    process_candle_refresh
)
from data_feed.data_cache_store import RAMCacheStore
from data_feed.csv_time_sync import TimeSyncManager
from monitoring.console_dashboard import ConsoleUI

logger = logging.getLogger(__name__)

# Gap thresholds (will be loaded from config)
_M1_GAP_SEC = 300    # > 5 min gap on M1 → re-fetch 200 candles
_M5_GAP_SEC = 1500   # > 25 min gap on M5 → re-fetch 200 candles
_M15_GAP_SEC = 4500  # > 75 min gap on M15 → re-fetch 200 candles


class DataAdapter(IDataSource):
    """
    Adapter for data translation, CSV management, and Market Ingestion Commander.
    Acts as Commander orchestrating DataValidator, CandleProcessor, RAMCacheStore, and Broker Connections.
    """

    def __init__(
        self,
        broker_adapter: Optional[IDataSource] = None,
        time_sync_manager: Optional[Any] = None,
        base_dir: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize DataAdapter.

        Args:
            broker_adapter: Broker instance implementing IDataSource (optional; auto-created if None)
            time_sync_manager: TimeSyncManager instance (optional; auto-created if None)
            base_dir: Base directory for CSV files (optional)
            config: Configuration from settings.json
        """
        # Initialize with configuration
        if config is None:
            from config_setting.config_loader import load_settings
            full_settings = load_settings(reload=True)
            df_config = full_settings.get("data_feed", {})
        elif "data_feed" in config:
            df_config = config.get("data_feed", {})
        else:
            df_config = config
        
        super().__init__(df_config)
        
        # Load data adapter configuration
        adapter_config = df_config.get("data_adapter", {})
        
        if broker_adapter is None:
            from data_feed.bridge_adapter.broker_factory import BrokerFactory
            from config_setting.config_loader import load_settings
            broker_adapter = BrokerFactory.create_raw_broker(config=load_settings(reload=False))
            
        self._broker = broker_adapter

        if base_dir is None:
            from config_setting.config_loader import get_csv_manager_config
            csv_mgr_cfg = get_csv_manager_config()
            base_dir = csv_mgr_cfg.get("base_dir", "data_feed/ohclv_output/iq_option")

        self._csv_manager = CSVManager(base_dir, df_config.get("csv_manager", {}))
        self._csv_queue = CSVQueue(df_config.get("csv_queue", {}))
        
        if time_sync_manager is None:
            time_sync_manager = TimeSyncManager(data_adapter=self._broker)
            time_sync_manager.sync_server_time(self._broker)
            time_sync_manager.start_time_sync_thread()

        self.time_calendar_mgr = time_sync_manager

        # Load configuration parameters
        self.default_candle_count = adapter_config.get("default_candle_count", 250)
        self.min_candle_count = adapter_config.get("min_candle_count", 21)
        self.m5_seconds = adapter_config.get("m5_seconds", 300)
        self.m15_seconds = adapter_config.get("m15_seconds", 900)
        self.auto_reconnect = adapter_config.get("auto_reconnect", True)
        
        # Zero Tolerance compliance check
        retry_attempts = adapter_config.get("retry_attempts", 0)
        retry_delay = adapter_config.get("retry_delay", 0)
        if retry_attempts > 0 or retry_delay > 0:
            logger.error(f"[DataAdapter] Zero Tolerance VIOLATION: retry_attempts={retry_attempts}, retry_delay={retry_delay}")
            logger.error(f"[DataAdapter] Config must have retry_attempts=0 and retry_delay=0")
            raise RuntimeError("Zero Tolerance: retry mechanisms not allowed")
        
        self.retry_attempts = 0  # Zero Tolerance: no retry allowed
        self.retry_delay = 0  # Zero Tolerance: no retry delay
        self.enable_cache = adapter_config.get("enable_cache", True)
        self.cache_size = adapter_config.get("cache_size", 1000)
        self.enable_csv_export = bool(df_config.get("enable_csv_export", True))
        
        # Initialize RAM cache store
        self._cache = RAMCacheStore()
        
        # Initialize validator
        self._validator = DataValidator()

        # Track ready symbols from warmup
        self.ready_symbols: List[str] = []
        
        logger.info(f"[DataAdapter] Initialized Commander (enable_csv_export={self.enable_csv_export}) with Zero Tolerance compliance")

    def read_csv(self, file_path: str, **kwargs) -> pd.DataFrame:
        """
        Read CSV file using thread synchronization lock.
        Ensures thread-safe read while CSVWriter or other threads perform writes.
        """
        if not isinstance(file_path, str):
            raise TypeError("file_path must be a string")
        return read_csv_safe(file_path, **kwargs)

    def read_symbol_csv(self, symbol: str, timeframe: str, **kwargs) -> pd.DataFrame:
        """
        Read CSV file for a given symbol and timeframe in a thread-safe manner.
        """
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        if not isinstance(timeframe, str):
            raise TypeError("timeframe must be a string")
        file_path = self._csv_manager.get_file_path(symbol, timeframe)
        df = self.read_csv(file_path, **kwargs)
        return DataValidator.ensure_utc_datetime_index(df)

    def init_symbol(self, symbol: str, broker_epoch: Optional[float] = None) -> bool:
        """Warm-up a symbol: fetch candles, validate, store in RAM, and write CSV.

        Args:
            symbol: Trading symbol.
            broker_epoch: Broker-synced epoch (from TimeSyncManager.get_broker_epoch()).
                If None, uses self.time_calendar_mgr.get_broker_epoch().
        """
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        if broker_epoch is None:
            broker_epoch = self.time_calendar_mgr.get_broker_epoch()

        try:
            # Fetch initial candles (extra buffer so after drop_forming, count >= 250 for all timeframes)
            m1 = self._broker.get_candles(symbol, 'M1', 255, end_time=broker_epoch)
            m5 = self._broker.get_candles(symbol, 'M5', 255, end_time=broker_epoch)
            m15 = self._broker.get_candles(symbol, 'M15', 255, end_time=broker_epoch)

            if (m1 is None or m1.empty or len(m1) < 2) or \
               (m5 is None or m5.empty or len(m5) < 2) or \
               (m15 is None or m15.empty or len(m15) < 2):
                raise ValueError("Incomplete data during init_symbol — all timeframes (M1, M5, M15) must be fetched directly from broker")

            # Validate data using DataValidator
            self._validator.validate(m1, symbol)
            self._validator.validate(m5, symbol)
            self._validator.validate(m15, symbol)

            # Store data in cache
            self._cache.set_store_data('M1', symbol, m1)
            self._cache.set_store_data('M5', symbol, m5)
            self._cache.set_store_data('M15', symbol, m15)

            # Set initial last_block to current time block
            self._cache.set_last_block_value('M1', symbol, TimeSyncManager.calculate_time_block(broker_epoch, 60))
            self._cache.set_last_block_value('M5', symbol, TimeSyncManager.calculate_time_block(broker_epoch, self.m5_seconds))
            self._cache.set_last_block_value('M15', symbol, TimeSyncManager.calculate_time_block(broker_epoch, self.m15_seconds))

            # Drop the still-forming last candle on each timeframe using broker_epoch and retain 250 completed
            m1_completed = drop_forming(m1, broker_epoch, 60).tail(250)
            m5_completed = drop_forming(m5, broker_epoch, 300).tail(250)
            m15_completed = drop_forming(m15, broker_epoch, 900).tail(250)

            # Add age and quality columns to initial candles using broker_epoch
            m1_completed = add_age_and_quality(m1_completed, broker_epoch, 60)
            m5_completed = add_age_and_quality(m5_completed, broker_epoch, 300)
            m15_completed = add_age_and_quality(m15_completed, broker_epoch, 900)

            # Store completed candles in RAM cache
            self._cache.set_completed_candles(symbol, {
                'M1': m1_completed,
                'M5': m5_completed,
                'M15': m15_completed
            })

            # Enqueue write to CSV files on SSD disk for all 3 timeframes (if enabled)
            if self.enable_csv_export:
                for tf, df in [('M1', m1_completed), ('M5', m5_completed), ('M15', m15_completed)]:
                    file_path = self._csv_manager.get_file_path(symbol, tf)
                    self._csv_queue.enqueue_write(df, file_path)

            logger.info(f"[DataAdapter] {symbol} initialised in RAM (CSV Export: {self.enable_csv_export}) — M1:{len(m1_completed)} M5:{len(m5_completed)} M15:{len(m15_completed)}")
            return True

        except Exception as e:
            logger.exception(f"[DataAdapter] Failed to init {symbol}: {e}")
            raise

    initialize = init_symbol

    def _wait_staggered_timing(self, target_second: float, broker_epoch: float) -> float:
        """
        Wait until target_second offset within the current minute:
        - M1  at :01.500 (target_second = 1.5)
        - M5  at :02.000 (target_second = 2.0)
        - M15 at :02.500 (target_second = 2.5)

        Returns the updated broker epoch at wake up.
        """
        if not isinstance(target_second, (int, float)):
            raise TypeError("target_second must be float or int")
        if not isinstance(broker_epoch, (int, float)):
            raise TypeError("broker_epoch must be float or int")

        minute_start = int(broker_epoch) - (int(broker_epoch) % 60)
        target_epoch = minute_start + target_second
        current_epoch = self.time_calendar_mgr.get_broker_epoch()
        wait_sec = target_epoch - current_epoch

        if wait_sec > 0:
            time.sleep(wait_sec)
            current_epoch = self.time_calendar_mgr.get_broker_epoch()

        return current_epoch

    def update(self, symbol: str, broker_epoch: Optional[float] = None) -> str:
        """Refresh candle stores, update RAM cache, and write CSV files. Returns symbol string on success."""
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        if broker_epoch is None:
            broker_epoch = self.time_calendar_mgr.get_broker_epoch()
        if not isinstance(broker_epoch, (int, float)):
            raise TypeError("broker_epoch must be a float or int")

        try:
            logger.info(f"[DataAdapter] Starting update for {symbol}")

            # 1. Staggered Step 1: M1 fetch at second :01.500
            broker_epoch_m1 = self._wait_staggered_timing(1.5, broker_epoch)
            current_block_m1 = TimeSyncManager.calculate_time_block(broker_epoch_m1, 60)

            # Refresh M1 data using process_candle_refresh
            completed_m1, m1_changed = process_candle_refresh(
                symbol=symbol,
                broker_epoch=broker_epoch_m1,
                store_dict=self._cache.get_store('M1'),
                last_block_dict=self._cache.get_last_block('M1'),
                data_source=self._broker,
                timeframe='M1',
                tf_seconds=60,
                max_candles=250,
                gap_threshold=_M1_GAP_SEC,
                validator=self._validator,
                current_block=current_block_m1
            )
            if completed_m1 is None:
                raise ValueError("M1 refresh failed")

            # 2. Staggered Step 2: M5 fetch at second :02.000 (when 5-min block closes)
            current_block_m5 = TimeSyncManager.calculate_time_block(broker_epoch, self.m5_seconds)
            last_block_m5 = self._cache.get_last_block('M5').get(symbol)
            m5_needs_fetch = (self._cache.get_store('M5').get(symbol) is None) or (current_block_m5 != last_block_m5)

            if m5_needs_fetch:
                broker_epoch_m5 = self._wait_staggered_timing(2.0, broker_epoch)
                current_block_m5 = TimeSyncManager.calculate_time_block(broker_epoch_m5, self.m5_seconds)
            else:
                broker_epoch_m5 = broker_epoch_m1

            # Refresh M5 data using process_candle_refresh
            completed_m5, m5_changed = process_candle_refresh(
                symbol=symbol,
                broker_epoch=broker_epoch_m5,
                store_dict=self._cache.get_store('M5'),
                last_block_dict=self._cache.get_last_block('M5'),
                data_source=self._broker,
                timeframe='M5',
                tf_seconds=300,
                max_candles=250,
                gap_threshold=_M5_GAP_SEC,
                validator=self._validator,
                current_block=current_block_m5
            )
            if completed_m5 is None:
                raise ValueError("M5 refresh failed")

            # 3. Staggered Step 3: M15 fetch at second :02.500 (when 15-min block closes)
            current_block_m15 = TimeSyncManager.calculate_time_block(broker_epoch, self.m15_seconds)
            last_block_m15 = self._cache.get_last_block('M15').get(symbol)
            m15_needs_fetch = (self._cache.get_store('M15').get(symbol) is None) or (current_block_m15 != last_block_m15)

            if m15_needs_fetch:
                broker_epoch_m15 = self._wait_staggered_timing(2.5, broker_epoch)
                current_block_m15 = TimeSyncManager.calculate_time_block(broker_epoch_m15, self.m15_seconds)
            else:
                broker_epoch_m15 = broker_epoch_m5

            # Refresh M15 data using process_candle_refresh
            completed_m15, m15_changed = process_candle_refresh(
                symbol=symbol,
                broker_epoch=broker_epoch_m15,
                store_dict=self._cache.get_store('M15'),
                last_block_dict=self._cache.get_last_block('M15'),
                data_source=self._broker,
                timeframe='M15',
                tf_seconds=900,
                max_candles=250,
                gap_threshold=_M15_GAP_SEC,
                validator=self._validator,
                current_block=current_block_m15
            )
            if completed_m15 is None:
                raise ValueError("M15 refresh failed")

            # Store completed candles in RAM cache
            self._cache.set_completed_candles(symbol, {
                'M1': completed_m1,
                'M5': completed_m5,
                'M15': completed_m15
            })

            # Enqueue write to CSV files ONLY when a new candle completed (and CSV export is enabled)
            if self.enable_csv_export:
                for tf, df, changed in [('M1', completed_m1, m1_changed), ('M5', completed_m5, m5_changed), ('M15', completed_m15, m15_changed)]:
                    if changed:
                        file_path = self._csv_manager.get_file_path(symbol, tf)
                        self._csv_queue.enqueue_write(df, file_path)

            # Return symbol string on successful update
            return symbol

        except Exception as e:
            logger.error(f"[DataAdapter] update failed for {symbol}: {e}")
            logger.error(f"[DataAdapter] Zero Tolerance: stopping immediately - no retry allowed")
            raise DataFeedError(f"Zero Tolerance: update failed for {symbol}: {e}") from e

    # ── RAM Access Methods (No Disk I/O) ─────────────────────────────
    def get_candles_ram(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """Return completed candles directly from RAM. No CSV read."""
        return self._cache.get_candles_ram(symbol)

    def export_csv(self, symbol: Optional[str] = None) -> None:
        """
        On-Demand CSV Export: Dump completed candles from RAM to CSV files.
        Can be triggered anytime Boss wants to inspect CSV files on disk.
        """
        symbols_to_export = [symbol] if symbol else list(self._cache._completed_candles.keys())
        for sym in symbols_to_export:
            candles = self._cache.get_candles_ram(sym)
            for tf, df in candles.items():
                file_path = self._csv_manager.get_file_path(sym, tf)
                self._csv_queue.enqueue_write(df, file_path)
        logger.info(f"[DataAdapter] On-demand CSV export queued for: {symbols_to_export}")
    
    def get_candles(self, symbol: str, timeframe: str = 'M1', 
                    count: int = 250, end_time: Optional[float] = None) -> pd.DataFrame:
        """ดึงข้อมูลแท่งเทียนจาก broker adapter"""
        return self._broker.get_candles(symbol, timeframe, count, end_time)
    
    def get_server_timestamp(self) -> float:
        """Get server timestamp (delegated to broker adapter)."""
        return self._broker.get_server_timestamp()

    def get_latest_close(self, symbol: str) -> float:
        """Return latest M1 close price from RAM. No CSV read."""
        return self._cache.get_latest_close(symbol)

    def check_warmup(self, symbol: str) -> bool:
        """Check warmup data sufficiency from RAM. No CSV read."""
        return self._cache.check_warmup(symbol)

    # ── Commander Level Methods (Part 1 Commander) ───────────────────
    @property
    def api(self) -> Any:
        """Access underlying broker API object (e.g. iqoptionapi instance)."""
        return getattr(self._broker, "api", None)

    @property
    def broker(self) -> IDataSource:
        """Access underlying broker adapter."""
        return self._broker

    def warmup_all_symbols(self, symbols: List[str]) -> bool:
        """
        Commander method: Warm up 250 historical candles for all symbols concurrently.
        Fetches M1, M5, M15 candles, validates data, stores in RAM, and writes 8-column CSV to disk.
        """
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("FAIL-FAST: symbols must be a non-empty list of strings")
        for sym in symbols:
            if not isinstance(sym, str):
                raise TypeError(f"FAIL-FAST: symbol must be a string, got {type(sym).__name__}")

        self.ensure_connected()
        warmup_epoch = self.time_calendar_mgr.get_broker_epoch()
        logger.info(f"[DataAdapter] Starting Commander warm-up for {len(symbols)} symbols at epoch {warmup_epoch}")

        ready_symbols: List[str] = []
        failed_symbols: List[str] = []

        max_workers = max(1, min(len(symbols), 20))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="WarmupWorker") as executor:
            future_to_sym = {
                executor.submit(self._warmup_single_symbol, sym, warmup_epoch): sym
                for sym in symbols
            }
            for future in concurrent.futures.as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    is_ready, err = future.result()
                    if is_ready:
                        ready_symbols.append(sym)
                    else:
                        failed_symbols.append(sym)
                        logger.warning(f"[DataAdapter] Warmup for {sym} failed: {err}")
                except Exception as e:
                    failed_symbols.append(sym)
                    logger.exception(f"[DataAdapter] Exception during warmup for {sym}: {e}")

        # Flush CSV queue to guarantee all 8-column CSV files are physically written to disk
        if self.enable_csv_export:
            self._csv_queue.flush()

        self.ready_symbols = ready_symbols
        logger.info(
            f"[DataAdapter] Commander warm-up completed: {len(ready_symbols)} ready ({ready_symbols}), "
            f"{len(failed_symbols)} failed/skipped"
        )

        if not self.ready_symbols:
            raise RuntimeError("FAIL-FAST: Zero assets passed historical data warm-up")

        return True

    def _warmup_single_symbol(self, symbol: str, warmup_epoch: float) -> Tuple[bool, Optional[str]]:
        """Internal worker for single symbol historical warm-up."""
        try:
            if self.init_symbol(symbol, broker_epoch=warmup_epoch):
                return True, None
            return False, "init_symbol returned False"
        except Exception as e:
            return False, str(e)

    def ingest_cycle(self, symbols: List[str]) -> Dict[str, float]:
        """
        Commander method: Ingest candle cycle across all symbols concurrently.
        Fetches completed candles, updates RAM cache, enqueues CSV export, and returns latest close prices.
        """
        if not isinstance(symbols, list):
            raise TypeError(f"FAIL-FAST: symbols must be a list of strings, got {type(symbols).__name__}")
        for sym in symbols:
            if not isinstance(sym, str):
                raise TypeError(f"FAIL-FAST: symbol must be a string, got {type(sym).__name__}")

        self.ensure_connected()
        cycle_broker_epoch = self.time_calendar_mgr.get_broker_epoch()
        logger.info(f"[DataAdapter] Commander cycle ingestion for {len(symbols)} symbols at epoch {cycle_broker_epoch}")

        prices_dict: Dict[str, float] = {}
        max_workers = max(1, min(len(symbols), 20))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="IngestWorker") as executor:
            future_to_sym = {
                executor.submit(self._ingest_single_symbol, sym, cycle_broker_epoch): sym
                for sym in symbols
            }
            for future in concurrent.futures.as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    price, err = future.result()
                    if price is not None:
                        prices_dict[sym] = price
                    else:
                        logger.warning(f"[DataAdapter] Ingest for {sym} returned no price: {err}")
                except Exception as e:
                    logger.exception(f"[DataAdapter] Exception during ingest for {sym}: {e}")

        # Flush CSV queue to make fresh data immediately available to Part 2 on disk
        if self.enable_csv_export:
            self._csv_queue.flush()

        # Get balance and display prices on Console UI
        balance = self.get_balance()
        ordered_prices = {sym: prices_dict[sym] for sym in symbols if sym in prices_dict}
        ConsoleUI.show_prices_and_balance(ordered_prices, balance)

        return prices_dict

    def _ingest_single_symbol(self, symbol: str, cycle_broker_epoch: float) -> Tuple[Optional[float], Optional[str]]:
        """Internal worker for single symbol candle ingestion."""
        try:
            update_res = self.update(symbol, broker_epoch=cycle_broker_epoch)
            if not update_res or not self.check_warmup(symbol):
                return None, "Warmup check failed after update"
            price = self.get_latest_close(symbol)
            return price, None
        except Exception as e:
            return None, str(e)

    def is_connected(self) -> bool:
        """Check connection status."""
        return bool(self._broker.is_connected())

    def connect(self) -> None:
        """Connect to data source."""
        return self._broker.connect()

    def disconnect(self) -> None:
        """Disconnect from data source."""
        if self._broker is not None:
            return self._broker.disconnect()

    def start_stream(self, symbol: str, timeframe: str, count: int) -> None:
        """Start streaming for symbol and timeframe."""
        return self._broker.start_stream(symbol, timeframe, count)

    def ensure_connected(self) -> bool:
        """Ensure connection is active, reconnect if needed."""
        res = self._broker.ensure_connected()
        return bool(res) if res is not None else self.is_connected()

    def get_balance(self) -> float:
        """Get account balance (delegated to broker adapter)."""
        return float(self._broker.get_balance())

    def get_open_symbols(self, target_symbols: Optional[List[str]] = None) -> List[str]:
        """Check and return list of open symbols (delegated to broker adapter)."""
        return self._broker.get_open_symbols(target_symbols)


