"""
RAM Cache Store - In-Memory Candle Storage Management

หน้าที่: จัดการแคชใน RAM สำหรับ candle data รวมถึงการเก็บและดึงข้อมูล
ฟังก์ชัน: _store_m1, _store_m5, _store_m15, _completed_candles, get_candles_ram, get_latest_close
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class RAMCacheStore:
    """RAM cache store for candle data management."""
    
    def __init__(self):
        """Initialize RAMCacheStore with empty stores."""
        # Per-symbol candle stores (raw data from broker)
        self._store_m1: Dict[str, Optional[pd.DataFrame]] = {}
        self._store_m5: Dict[str, Optional[pd.DataFrame]] = {}
        self._store_m15: Dict[str, Optional[pd.DataFrame]] = {}
        
        # Completed candles cache — RAM-only, no disk write
        self._completed_candles: Dict[str, Dict[str, pd.DataFrame]] = {}
        
        # Track last written block indices to avoid redundant disk writes
        self._last_block_m1: Dict[str, int] = {}
        self._last_block_m5: Dict[str, int] = {}
        self._last_block_m15: Dict[str, int] = {}
        
        
        logger.info("[RAMCacheStore] Initialized with empty cache")
    
    def get_store(self, timeframe: str) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Get the store dictionary for a specific timeframe.
        
        Args:
            timeframe: Timeframe string (M1, M5, M15)
            
        Returns:
            Dict[str, Optional[pd.DataFrame]]: Store dictionary
            
        Raises:
            ValueError: If timeframe is invalid
        """
        if timeframe == 'M1':
            return self._store_m1
        elif timeframe == 'M5':
            return self._store_m5
        elif timeframe == 'M15':
            return self._store_m15
        else:
            raise ValueError(f"Invalid timeframe: {timeframe}")
    
    def get_last_block(self, timeframe: str) -> Dict[str, int]:
        """
        Get the last block dictionary for a specific timeframe.
        
        Args:
            timeframe: Timeframe string (M1, M5, M15)
            
        Returns:
            Dict[str, int]: Last block dictionary
            
        Raises:
            ValueError: If timeframe is invalid
        """
        if timeframe == 'M1':
            return self._last_block_m1
        elif timeframe == 'M5':
            return self._last_block_m5
        elif timeframe == 'M15':
            return self._last_block_m15
        else:
            raise ValueError(f"Invalid timeframe: {timeframe}")
    
    def set_store_data(self, timeframe: str, symbol: str, df: pd.DataFrame) -> None:
        """
        Set data in the store for a specific timeframe and symbol.
        
        Args:
            timeframe: Timeframe string (M1, M5, M15)
            symbol: Trading symbol
            df: DataFrame to store
            
        Raises:
            ValueError: If timeframe is invalid
        """
        store = self.get_store(timeframe)
        store[symbol] = df
        logger.debug(f"[RAMCacheStore] Stored {timeframe} data for {symbol}: {len(df) if df is not None else 0} candles")
    
    def get_store_data(self, timeframe: str, symbol: str) -> Optional[pd.DataFrame]:
        """
        Get data from the store for a specific timeframe and symbol.
        
        Args:
            timeframe: Timeframe string (M1, M5, M15)
            symbol: Trading symbol
            
        Returns:
            Optional[pd.DataFrame]: Stored DataFrame or None
            
        Raises:
            ValueError: If timeframe is invalid
        """
        store = self.get_store(timeframe)
        return store.get(symbol)
    
    def get_last_block_value(self, timeframe: str, symbol: str) -> int:
        """
        Get the last block value for a specific timeframe and symbol.
        
        Args:
            timeframe: Timeframe string (M1, M5, M15)
            symbol: Trading symbol
            
        Returns:
            int: Last block value (defaults to -1 if not set)
            
        Raises:
            ValueError: If timeframe is invalid
        """
        block_dict = self.get_last_block(timeframe)
        return block_dict.get(symbol, -1)
    
    def set_last_block_value(self, timeframe: str, symbol: str, block: int) -> None:
        """
        Set the last block value for a specific timeframe and symbol.
        
        Args:
            timeframe: Timeframe string (M1, M5, M15)
            symbol: Trading symbol
            block: Block index value
            
        Raises:
            ValueError: If timeframe is invalid
        """
        block_dict = self.get_last_block(timeframe)
        block_dict[symbol] = block
        logger.debug(f"[RAMCacheStore] Updated last block for {timeframe} {symbol}: {block}")
    
    def set_completed_candles(self, symbol: str, candles: Dict[str, pd.DataFrame]) -> None:
        """
        Set completed candles in RAM cache.
        
        Args:
            symbol: Trading symbol
            candles: Dictionary of timeframe to DataFrame mappings
        """
        self._completed_candles[symbol] = candles
        logger.debug(f"[RAMCacheStore] Updated completed candles for {symbol}: {len(candles)} timeframes")
    
    def get_completed_candles(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """
        Get completed candles from RAM cache.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dict[str, pd.DataFrame]: Dictionary of timeframe to DataFrame mappings
            
        Raises:
            ValueError: If symbol not found in cache
        """
        if symbol not in self._completed_candles:
            raise ValueError(f"FAIL-FAST: No candle data in RAM for {symbol}")
        
        return self._completed_candles[symbol]
    
    def get_candles_ram(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """
        Return completed candles directly from RAM. No CSV read.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dict[str, pd.DataFrame]: Dictionary of timeframe to DataFrame mappings
            
        Raises:
            TypeError: If symbol is not a string
            ValueError: If symbol not found in cache
        """
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        
        return self.get_completed_candles(symbol)
    
    def get_latest_close(self, symbol: str) -> float:
        """
        Return latest real-time M1 close price from RAM (_store_m1 or completed). No CSV read.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            float: Latest M1 close price
            
        Raises:
            TypeError: If symbol is not a string
            ValueError: If M1 data not found or empty
        """
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        
        # 1. Try raw real-time stream store first (contains forming/live candle)
        store_m1 = self._store_m1.get(symbol)
        if store_m1 is not None and not store_m1.empty and 'close' in store_m1.columns:
            return float(store_m1['close'].iloc[-1])
            
        # 2. Fallback to completed candles if raw store is not yet initialized
        candles = self._completed_candles.get(symbol)
        if candles is None or 'M1' not in candles:
            raise ValueError(f"FAIL-FAST: No M1 data in RAM for {symbol}")
        
        m1 = candles['M1']
        if m1.empty or 'close' not in m1.columns:
            raise ValueError(f"FAIL-FAST: M1 data empty or missing 'close' column for {symbol}")
        
        return float(m1['close'].iloc[-1])
    
    def check_warmup(self, symbol: str) -> bool:
        """
        Check warmup data sufficiency from RAM. No CSV read.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            bool: True if warmup data is sufficient, False otherwise
            
        Raises:
            TypeError: If symbol is not a string
        """
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string")
        
        reqs = {"M1": 250, "M5": 250, "M15": 250}
        candles = self._completed_candles.get(symbol)
        
        if candles is None:
            logger.warning(f"[{symbol}] No candle data in RAM")
            return False
        
        for tf, req_len in reqs.items():
            df = candles.get(tf)
            if df is None or len(df) < req_len:
                logger.warning(f"[{symbol}] Insufficient {tf} data in RAM: has {len(df) if df is not None else 0}, required >= {req_len}")
                return False
        
        return True
    
    def has_data(self, symbol: str) -> bool:
        """
        Check if symbol has data in RAM cache.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            bool: True if data exists, False otherwise
        """
        return symbol in self._completed_candles
    
    def clear_symbol(self, symbol: str) -> None:
        """
        Clear all cache data for a specific symbol.
        
        Args:
            symbol: Trading symbol
        """
        # Clear stores
        if symbol in self._store_m1:
            del self._store_m1[symbol]
        if symbol in self._store_m5:
            del self._store_m5[symbol]
        if symbol in self._store_m15:
            del self._store_m15[symbol]
        
        # Clear completed candles
        if symbol in self._completed_candles:
            del self._completed_candles[symbol]
        
        # Clear block indices
        if symbol in self._last_block_m1:
            del self._last_block_m1[symbol]
        if symbol in self._last_block_m5:
            del self._last_block_m5[symbol]
        if symbol in self._last_block_m15:
            del self._last_block_m15[symbol]
        
        logger.info(f"[RAMCacheStore] Cleared all cache data for {symbol}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the cache.
        
        Returns:
            Dict[str, Any]: Cache statistics
        """
        stats = {
            'symbols': list(self._completed_candles.keys()),
            'total_symbols': len(self._completed_candles),
            'store_m1_count': len(self._store_m1),
            'store_m5_count': len(self._store_m5),
            'store_m15_count': len(self._store_m15),
            'completed_candles_count': len(self._completed_candles),
        }
        
        # Add candle counts per symbol
        candle_counts = {}
        for symbol, candles in self._completed_candles.items():
            counts = {}
            for tf, df in candles.items():
                counts[tf] = len(df) if df is not None else 0
            candle_counts[symbol] = counts
        stats['candle_counts'] = candle_counts
        
        return stats
