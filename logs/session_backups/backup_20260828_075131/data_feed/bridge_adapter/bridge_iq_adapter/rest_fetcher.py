"""
IQ Option REST Candle Fetcher

Handles synchronous thread-safe REST candle fetching with hard per-call timeout,
data normalization, and Zero Tolerance integrity validations.
"""

import concurrent.futures
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Optional, Any, Dict, List
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Global lock — iqoptionapi shares a single websocket buffer
_CANDLES_LOCK = threading.Lock()

# Timeframe mapping to IQ Option candle sizes (in seconds)
_TF_SECONDS: Dict[str, int] = {
    'M1': 60,
    'M5': 300,
    'M15': 900,
    'M30': 1800,
    'M60': 3600,
    'H1': 3600,
    'H4': 14400,
    'D1': 86400,
}


class IQRestFetcher:
    """Handles REST candle requests and data processing for IQ Option."""

    def __init__(self, timeout_sec: int = 8, max_workers: int = 10):
        self.timeout_sec: int = timeout_sec
        self.max_workers: int = max_workers
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)

    @property
    def supported_timeframes(self) -> Dict[str, int]:
        """Return supported timeframe mappings."""
        return _TF_SECONDS

    @staticmethod
    def normalize_candle_index(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize candle index to UTC DatetimeIndex."""
        if df is None or df.empty:
            raise ValueError("Empty DataFrame in normalize_candle_index")
        out = df.copy()
        if not isinstance(out.index, pd.DatetimeIndex):
            if pd.api.types.is_numeric_dtype(out.index):
                out.index = pd.to_datetime(out.index, unit='s', utc=True)
            else:
                out.index = pd.to_datetime(out.index, utc=True)
        elif out.index.tz is None:
            out.index = out.index.tz_localize('UTC')
        else:
            out.index = out.index.tz_convert('UTC')
        return out.sort_index(ascending=True)

    def fetch_candles(self, api: Any, symbol: str, timeframe: str = 'M1',
                      count: int = 200, end_time: Optional[Any] = None) -> pd.DataFrame:
        """
        Fetch candles from IQ Option REST API.
        
        Args:
            api: Active IQ_Option API instance
            symbol: Asset symbol (e.g. 'EURUSD-OTC')
            timeframe: Timeframe string ('M1', 'M5', etc.)
            count: Number of candles to fetch
            end_time: Optional end timestamp or datetime
            
        Returns:
            pd.DataFrame indexed by UTC DatetimeIndex with columns [open, high, low, close, volume]
        """
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        if not isinstance(timeframe, str):
            raise TypeError("timeframe must be a string")
        if not isinstance(count, int):
            raise TypeError("count must be an integer")
        if timeframe not in _TF_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe}. Supported: {list(_TF_SECONDS.keys())}")
        if api is None:
            raise RuntimeError("API not initialized")

        size = _TF_SECONDS[timeframe]

        # Parse end_time to epoch timestamp
        end_timestamp: float = time.time()
        if end_time is not None:
            if isinstance(end_time, datetime):
                end_timestamp = float(end_time.timestamp())
            elif isinstance(end_time, (int, float)):
                end_timestamp = float(end_time)

        # REST HTTP request bounded by hard per-call timeout
        def _fetch():
            acquired = _CANDLES_LOCK.acquire(timeout=self.timeout_sec)
            if not acquired:
                raise RuntimeError(f"Cannot acquire candle lock for {symbol} within {self.timeout_sec}s")
            try:
                return api.get_candles(symbol, size, count, end_timestamp)
            finally:
                _CANDLES_LOCK.release()

        future = self._executor.submit(_fetch)
        try:
            raw = future.result(timeout=self.timeout_sec)
            logger.info(f"[IQOPTION] REST fetch succeeded for {symbol}: {len(raw)} candles")
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error(f"[IQOPTION] REST fetch timed out for {symbol} after {self.timeout_sec}s")
            logger.error("[IQOPTION] Zero Tolerance: stopping immediately - no retry allowed")
            raise RuntimeError(f"REST fetch timed out for {symbol} after {self.timeout_sec}s")
        except Exception as e:
            logger.error(f"[IQOPTION] REST fetch failed for {symbol}: {e}")
            logger.error("[IQOPTION] Zero Tolerance: stopping immediately - no retry allowed")
            raise RuntimeError(f"REST fetch failed for {symbol}: {e}") from e

        if not raw:
            raise ValueError(f"REST fetch returned no data for {symbol}")

        df = pd.DataFrame(raw)
        if df.empty:
            raise ValueError(f"REST fetch returned empty dataframe for {symbol}")

        df = df.rename(columns={"max": "high", "min": "low"})
        need = {"from", "open", "close", "high", "low"}
        if not need.issubset(df.columns):
            raise ValueError(f"REST fetch missing required columns for {symbol}: {need - set(df.columns)}")

        df["timestamp"] = pd.to_datetime(df["from"], unit="s", utc=True)
        for col in ("open", "close", "high", "low"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        is_otc = "OTC" in symbol.upper()

        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            if df["volume"].isnull().any():
                raise ValueError(f"Volume contains NaN values for {symbol} - no fallback allowed")
        else:
            raise ValueError(f"Volume column missing for {symbol}")

        df = df.dropna(subset=["open", "close", "high", "low"])
        if df.empty:
            raise ValueError(f"Empty dataframe after dropna for {symbol}")

        # Zero Tolerance: reject non-OTC volume = 0
        if not is_otc and df["volume"].sum() == 0:
            raise ValueError(f"Volume is all zeros for non-OTC symbol {symbol} — broker data error")

        # Sanity check: reject obviously broken price feeds
        median_close = float(df["close"].median())
        is_jpy = "JPY" in symbol.upper()
        if is_jpy and not (50.0 <= median_close <= 300.0):
            raise ValueError(f"{symbol} median {median_close} out of JPY range")
        if not is_jpy and not (0.3 <= median_close <= 10.0):
            raise ValueError(f"{symbol} median {median_close} out of FX range")

        res = df[["timestamp", "open", "high", "low", "close", "volume"]].set_index("timestamp")
        res.index = pd.to_datetime(res.index, utc=True)
        return self.normalize_candle_index(res)
