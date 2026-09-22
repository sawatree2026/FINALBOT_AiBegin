"""
IQ Option WebSocket Stream Manager

Handles real-time WebSocket candle streaming, thread-safe memory cache access,
and streaming updates with Fail-Fast / Zero Tolerance compliance.
"""

import logging
import threading
import time
from typing import Optional, Any, Dict, List
import pandas as pd
from .rest_fetcher import _CANDLES_LOCK, _TF_SECONDS, IQRestFetcher

logger = logging.getLogger(__name__)


class IQStreamManager:
    """Manages real-time WebSocket candle subscriptions and memory cache."""

    def __init__(self, timeout_sec: int = 8):
        self.timeout_sec: int = timeout_sec
        self._cache_lock: threading.RLock = threading.RLock()

    def start_stream(self, api: Any, symbol: str, timeframe: str = 'M1', count: int = 200) -> None:
        """
        Start WebSocket candle streaming for a symbol and timeframe.
        """
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        if not isinstance(timeframe, str):
            raise TypeError("timeframe must be a string")
        if not isinstance(count, int):
            raise TypeError("count must be an integer")
        if timeframe not in _TF_SECONDS:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        if api is None:
            raise RuntimeError("API not initialized")

        size = _TF_SECONDS[timeframe]

        # Acquire lock to prevent race condition on WebSocket stream initiation
        acquired = _CANDLES_LOCK.acquire(timeout=self.timeout_sec)
        if not acquired:
            raise RuntimeError(f"Cannot acquire lock for stream {symbol} within {self.timeout_sec}s")
        try:
            logger.info(f"[STREAM] Starting candle stream for {symbol} ({timeframe}) count={count}")
            api.start_candles_stream(ACTIVE=symbol, size=size, maxdict=count)
        finally:
            _CANDLES_LOCK.release()

    def get_cached_candles(self, api: Any, symbol: str, timeframe: str = 'M1') -> Optional[pd.DataFrame]:
        """
        Thread-safe retrieval of cached realtime candles from IQ Option API.
        """
        if api is None or timeframe not in _TF_SECONDS:
            return None

        size = _TF_SECONDS[timeframe]
        with self._cache_lock:
            try:
                raw_dict = None
                # Check various places where iqoptionapi stores real-time candles
                inner_api = getattr(api, 'api', None)
                if inner_api is not None and hasattr(inner_api, 'real_time_candles'):
                    candles_store = getattr(inner_api, 'real_time_candles', {})
                    raw_dict = candles_store.get(symbol, {}).get(size, {})
                elif hasattr(api, 'real_time_candles'):
                    candles_store = getattr(api, 'real_time_candles', {})
                    raw_dict = candles_store.get(symbol, {}).get(size, {})
                elif hasattr(api, 'realtime_candles'):
                    candles_store = getattr(api, 'realtime_candles', {})
                    raw_dict = candles_store.get(symbol, {}).get(size, {})

                if not raw_dict and hasattr(api, 'get_realtime_candles'):
                    try:
                        res = api.get_realtime_candles(symbol, size)
                        if isinstance(res, (dict, list)) and res:
                            raw_dict = res
                    except Exception:
                        pass

                if not raw_dict:
                    return None

                # Convert dict of candles to sorted list
                if isinstance(raw_dict, dict):
                    candles_list = sorted(raw_dict.values(), key=lambda c: c.get('from', 0) if isinstance(c, dict) else 0)
                elif isinstance(raw_dict, list):
                    candles_list = sorted(raw_dict, key=lambda c: c.get('from', 0) if isinstance(c, dict) else 0)
                else:
                    return None

                if not candles_list:
                    return None

                df = pd.DataFrame(candles_list)
                if df.empty or 'from' not in df.columns:
                    return None

                df = df.rename(columns={"max": "high", "min": "low"})
                need = {"from", "open", "close", "high", "low"}
                if not need.issubset(df.columns):
                    return None

                df["timestamp"] = pd.to_datetime(df["from"], unit="s", utc=True)
                for col in ("open", "close", "high", "low"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                if "volume" in df.columns:
                    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype('int64')
                else:
                    df["volume"] = 0

                df = df.dropna(subset=["open", "close", "high", "low"])
                if df.empty:
                    return None

                res = df[["timestamp", "open", "high", "low", "close", "volume"]].set_index("timestamp")
                res.index = pd.to_datetime(res.index, utc=True)
                return IQRestFetcher.normalize_candle_index(res)
            except Exception as e:
                logger.warning(f"Error accessing cached candles for {symbol}: {e}")
                return None

    def update_with_streaming(self, api: Any, symbol: str, timeframe: str = 'M1', count: int = 200) -> pd.DataFrame:
        """
        Get latest candles using WebSocket streaming cache as Single Source of Truth,
        with automatic streaming start and REST bootstrapping fallback.
        """
        # 1. First attempt to read from WebSocket cache
        cached_df = self.get_cached_candles(api, symbol, timeframe)
        if cached_df is not None and len(cached_df) >= 2:
            return cached_df.tail(count)

        # 2. If stream not started or cache has insufficient data, start stream
        logger.info(f"[STREAM] WebSocket cache empty for {symbol} ({timeframe}), starting stream...")
        self.start_stream(api, symbol, timeframe, count=count)
        
        # Micro-polling: check cache every 20ms up to max 200ms, exit immediately as soon as data arrives
        max_wait = 0.20
        poll_interval = 0.02
        start_time = time.time()
        while time.time() - start_time < max_wait:
            time.sleep(poll_interval)
            cached_df = self.get_cached_candles(api, symbol, timeframe)
            if cached_df is not None and len(cached_df) >= 2:
                return cached_df.tail(count)

        # 4. If cache still not ready, bootstrap via REST fetcher
        logger.warning(f"[FALLBACK] WebSocket failed for {symbol} ({timeframe}) — using REST API fallback")
        fetcher = IQRestFetcher(self.timeout_sec)
        rest_df = fetcher.fetch_candles(api, symbol, timeframe, count)
        if rest_df is not None and not rest_df.empty:
            logger.warning(f"[FALLBACK] REST fallback succeeded for {symbol} ({timeframe}) — {len(rest_df)} candles retrieved")
            return rest_df.tail(count)

        # 5. Fail-fast if REST fetch also returned empty
        logger.error(f"[IQOPTION] WebSocket Cache and REST Bootstrap empty for {symbol} — Fail-Fast triggered")
        raise RuntimeError(f"FAIL-FAST: Failed to obtain candles for {symbol}. Data connection unavailable.")
