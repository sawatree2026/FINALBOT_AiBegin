"""
CSV Writer

Writes candle dataframes to CSV files.
"""

import os
import time
import threading
import traceback
import pandas as pd
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Global Per-File Lock Dictionary & Mutex (Using RLock for thread reentrancy safety)
_FILE_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_MUTEX = threading.Lock()

def get_file_lock(file_path: str) -> threading.RLock:
    """
    Get or create a reentrant thread lock per absolute file path.
    Ensures per-file thread synchronization across all readers and writers.
    """
    abs_path = os.path.abspath(file_path)
    with _LOCKS_MUTEX:
        if abs_path not in _FILE_LOCKS:
            _FILE_LOCKS[abs_path] = threading.RLock()
        return _FILE_LOCKS[abs_path]

def read_csv_safe(file_path: str, **kwargs) -> pd.DataFrame:
    """
    Read CSV file safely using the per-file thread lock to ensure zero-lock/zero-error reads.
    """
    file_lock = get_file_lock(file_path)
    with file_lock:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                return pd.read_csv(file_path, **kwargs)
            except PermissionError:
                if attempt < max_retries:
                    time.sleep(0.05)
                else:
                    raise


class CSVWriter:
    """Writes candle dataframes to CSV files with Thread-Safe synchronization - Singleton Pattern"""

    _instance = None
    _LISTENERS = []

    @classmethod
    def register_listener(cls, callback):
        """Register a callback to be triggered immediately when a CSV write completes: callback(file_path)."""
        if callback not in cls._LISTENERS:
            cls._LISTENERS.append(callback)

    @classmethod
    def unregister_listener(cls, callback):
        """Unregister a write listener callback."""
        if callback in cls._LISTENERS:
            cls._LISTENERS.remove(callback)

    def __new__(cls, *args, **kwargs):
        """Ensure singleton pattern for CSVWriter"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize with writer configuration.
        
        Args:
            config: Configuration from datafeed_config.json csv_writer section
        """
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self._initialized = True
        if config is None:
            from config_setting.config_loader import get_csv_writer_config
            config = get_csv_writer_config()
        
        # Load writer configuration
        self.encoding = config.get("encoding", "utf-8")
        self.date_format = config.get("date_format", "%Y-%m-%d %H:%M:%S")
        self.include_header = config.get("include_header", True)
        self.decimal_places = config.get("decimal_places", 6)
        
        logger.info(f"[CSVWriter] Initialized with encoding: {self.encoding}, decimals: {self.decimal_places}")

    def read(self, file_path: str, **kwargs) -> pd.DataFrame:
        """Read CSV file safely using per-file synchronization lock."""
        kwargs.setdefault("encoding", self.encoding)
        return read_csv_safe(file_path, **kwargs)

    def write(self, df: pd.DataFrame, file_path: str) -> None:
        """Write DataFrame to the specified file path inside a Per-File Lock."""
        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"df must be pd.DataFrame, got {type(df).__name__}")
        if not isinstance(file_path, str):
            raise TypeError(f"file_path must be str, got {type(file_path).__name__}")
        if df is None or df.empty:
            logger.warning(f"[CSVWriter] Attempted to write empty dataframe to {file_path}")
            raise ValueError(f"Cannot write empty dataframe to {file_path}")
            
        dir_path = os.path.dirname(file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        logger.info(f"[CSVWriter] Writing {len(df)} rows to {file_path}")
        
        # Prepare dataframe for writing
        df_to_write = df.copy()
        
        # If timestamp is in index and not in columns, reset index
        if 'timestamp' not in df_to_write.columns and isinstance(df_to_write.index, pd.DatetimeIndex):
            df_to_write = df_to_write.reset_index()
            if df_to_write.columns[0] != 'timestamp':
                df_to_write.rename(columns={df_to_write.columns[0]: 'timestamp'}, inplace=True)

        # Select ALL standard columns including timestamp (8 columns total)
        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'age', 'quality']
        df_to_write = df_to_write[[c for c in cols if c in df_to_write.columns]]
        
        file_lock = get_file_lock(file_path)
        with file_lock:
            # Read existing file if present using read_csv_safe (handles locking safely), merge and deduplicate
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                try:
                    existing_df = read_csv_safe(file_path, encoding=self.encoding)
                    if 'timestamp' in existing_df.columns:
                        existing_cols = [c for c in cols if c in existing_df.columns]
                        existing_df = existing_df[existing_cols]
                    else:
                        # timestamp อยู่ใน index — reset ออกมาเป็นคอลัมน์
                        existing_df = existing_df.reset_index()
                        if existing_df.columns[0] != 'timestamp':
                            existing_df.rename(columns={existing_df.columns[0]: 'timestamp'}, inplace=True)
                        existing_cols = [c for c in cols if c in existing_df.columns]
                        existing_df = existing_df[existing_cols]

                    existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'], utc=True)
                    df_to_write['timestamp'] = pd.to_datetime(df_to_write['timestamp'], utc=True)

                    combined_df = pd.concat([existing_df, df_to_write], ignore_index=True)
                    combined_df = combined_df.drop_duplicates(subset=['timestamp'], keep='last')
                    combined_df = combined_df.sort_values(by='timestamp').reset_index(drop=True)
                    df_to_write = combined_df.tail(250)
                except Exception as e:
                    logger.error(f"[CSVWriter] Could not merge with existing file {file_path}: {e}")
                    traceback.print_exc()
                    raise

            # Ensure strictly 250 latest rows and exact standard 8 columns order before writing
            df_to_write = df_to_write.tail(250)[[c for c in cols if c in df_to_write.columns]]
            
            # Format types explicitly after merge
            for col in ['open', 'high', 'low', 'close']:
                if col in df_to_write.columns:
                    df_to_write[col] = df_to_write[col].round(self.decimal_places)
            if 'volume' in df_to_write.columns:
                df_to_write['volume'] = df_to_write['volume'].fillna(0).round().astype('int64')
            if 'age' in df_to_write.columns:
                df_to_write['age'] = df_to_write['age'].round().astype('int64')
            if 'quality' in df_to_write.columns:
                df_to_write['quality'] = df_to_write['quality'].astype(str)

            # Format timestamp explicitly to UTC string so to_csv retains +00:00 (Standard ISO 8601)
            if 'timestamp' in df_to_write.columns:
                if not pd.api.types.is_datetime64_any_dtype(df_to_write['timestamp']):
                    df_to_write['timestamp'] = pd.to_datetime(df_to_write['timestamp'], utc=True)
                df_to_write['timestamp'] = df_to_write['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S+00:00')

            try:

                # Write to temporary file and replace atomically
                tmp_path = f"{file_path}.{threading.get_ident()}.tmp"
                df_to_write.to_csv(
                    path_or_buf=tmp_path,
                    encoding=self.encoding,
                    header=self.include_header,
                    index=False,
                    mode='w',
                    date_format=self.date_format
                )
                # Retry loop on PermissionError to handle Windows OS millisecond file handle release delays
                max_retries = 5
                for attempt in range(1, max_retries + 1):
                    try:
                        os.replace(tmp_path, file_path)
                        break
                    except PermissionError as pe:
                        if attempt < max_retries:
                            logger.warning(f"[CSVWriter] PermissionError on os.replace (attempt {attempt}/{max_retries}) for {file_path}, retrying in 0.05s... Error: {pe}")
                            time.sleep(0.05)
                        else:
                            logger.error(f"[CSVWriter] os.replace failed after {max_retries} attempts for {file_path}: {pe}")
                            if os.path.exists(tmp_path):
                                try:
                                    os.remove(tmp_path)
                                except Exception as rm_err:
                                    logger.warning(f"[CSVWriter] Failed to remove tmp file {tmp_path}: {rm_err}")
                            raise
                    except Exception as e:
                        logger.error(f"[CSVWriter] os.replace failed for {file_path}: {e}")
                        if os.path.exists(tmp_path):
                            try:
                                os.remove(tmp_path)
                            except Exception as rm_err:
                                logger.warning(f"[CSVWriter] Failed to remove tmp file {tmp_path}: {rm_err}")
                        raise
                
                logger.info(f"[CSVWriter] Successfully wrote {len(df_to_write)} rows to {file_path}")

                # Event-Driven Trigger (สะกิด Part 2 / Listeners ทันทีที่ไฟล์เขียนลงดิสก์เสร็จ)
                for listener in list(self._LISTENERS):
                    try:
                        listener(file_path)
                    except Exception as cb_err:
                        logger.warning(f"[CSVWriter] Listener callback error for {file_path}: {cb_err}")

            except Exception as e:
                logger.error(f"[CSVWriter] Failed to write to {file_path}: {e}")
                raise

