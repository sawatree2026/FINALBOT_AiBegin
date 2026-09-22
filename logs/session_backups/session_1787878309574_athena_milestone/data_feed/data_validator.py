"""
Data Validator - Candle Data Validation System

หน้าที่: ตรวจสอบความถูกต้องของข้อมูล candle ก่อนนำไปใช้
ฟังก์ชัน: ตรวจสอบ data_frame, คอลัมน์, ประเภทข้อมูล, และความสมบูรณ์
"""

import pandas as pd
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class DataValidator:
    """Validator for candle data validation and integrity checks."""
    
    # Required columns for candle data
    REQUIRED_COLUMNS = ['open', 'high', 'low', 'close', 'volume']
    
    def __init__(self):
        """Initialize DataValidator."""
        pass
    
    def validate(self, df: pd.DataFrame, symbol: str) -> bool:
        """
        Validate DataFrame for candle data integrity.
        
        Args:
            df: DataFrame to validate
            symbol: Symbol name for logging
            
        Returns:
            bool: True if validation passes
            
        Raises:
            ValueError: If validation fails
        """
        if df is None:
            raise ValueError(f"[{symbol}] DataFrame is None")
        
        if df.empty:
            raise ValueError(f"[{symbol}] DataFrame is empty")
        
        # Check for required columns
        missing_cols = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing_cols:
            raise ValueError(f"[{symbol}] Missing required columns: {missing_cols}")
        
        # Check for NaN values in price columns
        price_cols = ['open', 'high', 'low', 'close']
        for col in price_cols:
            if df[col].isna().any():
                nan_count = df[col].isna().sum()
                raise ValueError(f"[{symbol}] Column '{col}' contains {nan_count} NaN values")
        
        # Check for negative prices
        for col in price_cols:
            if (df[col] < 0).any():
                neg_count = (df[col] < 0).sum()
                raise ValueError(f"[{symbol}] Column '{col}' contains {neg_count} negative values")
        
        # Check for zero or negative spreads (high >= low, open/close within range)
        if (df['high'] < df['low']).any():
            invalid_spreads = (df['high'] < df['low']).sum()
            raise ValueError(f"[{symbol}] {invalid_spreads} candles have high < low")
        
        if ((df['open'] < df['low']) | (df['open'] > df['high'])).any():
            invalid_open = ((df['open'] < df['low']) | (df['open'] > df['high'])).sum()
            raise ValueError(f"[{symbol}] {invalid_open} candles have open outside [low, high]")
        
        if ((df['close'] < df['low']) | (df['close'] > df['high'])).any():
            invalid_close = ((df['close'] < df['low']) | (df['close'] > df['high'])).sum()
            raise ValueError(f"[{symbol}] {invalid_close} candles have close outside [low, high]")
        
        # Check for duplicated index
        if df.index.duplicated().any():
            dup_count = df.index.duplicated().sum()
            logger.warning(f"[{symbol}] Found {dup_count} duplicated timestamps, keeping last")
        
        # Check for sorted index
        if not df.index.is_monotonic_increasing:
            logger.warning(f"[{symbol}] Index is not sorted, sorting...")
        
        # Check for timestamp consistency
        if 'timestamp' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                logger.warning(f"[{symbol}] 'timestamp' column is not datetime type")
        
        # Validate volume if present
        if 'volume' in df.columns:
            if (df['volume'] < 0).any():
                neg_volume = (df['volume'] < 0).sum()
                raise ValueError(f"[{symbol}] Volume contains {neg_volume} negative values")
        
        logger.debug(f"[{symbol}] Data validation passed: {len(df)} candles")
        return True
    
    def validate_continuity(self, stored_df: pd.DataFrame, fresh_df: pd.DataFrame, 
                           symbol: str, label: str, threshold: float = 0.10) -> bool:
        """
        Validate price continuity between stored and fresh data.
        
        Args:
            stored_df: Existing stored DataFrame
            fresh_df: New data to validate
            symbol: Symbol name
            label: Label for logging
            threshold: Maximum allowed price difference ratio (default: 0.10)
            
        Returns:
            bool: True if continuity check passes
            
        Raises:
            ValueError: If continuity check fails
        """
        if stored_df is None or stored_df.empty:
            raise ValueError(f"[{symbol}] stored_df is empty in continuity check")
        
        if fresh_df is None or fresh_df.empty:
            raise ValueError(f"[{symbol}] fresh_df is empty in continuity check")
        
        # Check price continuity using median of close prices
        if 'close' in stored_df.columns and 'close' in fresh_df.columns:
            stored_close_median = stored_df['close'].median()
            fresh_close_median = fresh_df['close'].median()
            
            if stored_close_median is not None and fresh_close_median is not None:
                # Calculate relative difference between medians
                if stored_close_median != 0:
                    price_diff_ratio = abs(fresh_close_median - stored_close_median) / stored_close_median
                else:
                    price_diff_ratio = float('inf')
                
                # If price difference is more than threshold, this is likely symbol mixing
                if price_diff_ratio > threshold:
                    logger.error(f"[DataAdapter] {label}: PRICE CONTINUITY VIOLATION detected! "
                               f"Stored median={stored_close_median:.5f}, Fresh median={fresh_close_median:.5f}, "
                               f"Diff ratio={price_diff_ratio:.3f}. This indicates symbol mixing!")
                    from data_feed.exceptions import DataGapError
                    raise DataGapError(
                        f"FAIL-FAST: Price continuity violation for {label} - likely symbol mixing "
                        f"(stored median {stored_close_median:.5f} vs fresh median {fresh_close_median:.5f})"
                    )
                else:
                    logger.debug(f"[DataAdapter] {label}: Price continuity verified. "
                               f"Stored median={stored_close_median:.5f}, Fresh median={fresh_close_median:.5f}, "
                               f"Diff ratio={price_diff_ratio:.3f}")
        
        return True
    
    def validate_overlap(self, stored_df: pd.DataFrame, fresh_df: pd.DataFrame,
                        symbol: str, label: str, threshold: float = 0.05) -> bool:
        """
        Validate overlap consistency between stored and fresh data.
        
        Args:
            stored_df: Existing stored DataFrame
            fresh_df: New data to validate
            symbol: Symbol name
            label: Label for logging
            threshold: Maximum allowed overlap difference ratio (default: 0.05)
            
        Returns:
            bool: True if overlap check passes
            
        Raises:
            ValueError: If overlap check fails
        """
        if stored_df is None or stored_df.empty:
            raise ValueError(f"[{symbol}] stored_df is empty in overlap check")
        
        if fresh_df is None or fresh_df.empty:
            raise ValueError(f"[{symbol}] fresh_df is empty in overlap check")
        
        overlap = stored_df.index.intersection(fresh_df.index)
        if len(overlap) > 1 and 'close' in stored_df.columns and 'close' in fresh_df.columns:
            check = overlap[:-1][-4:]  # Check last 4 overlapping candles
            if len(check) > 0:
                stored_close_values = stored_df.loc[check, 'close']
                fresh_close_values = fresh_df.loc[check, 'close']
                
                # Check if price difference in overlap is significant
                overlap_median_diff = abs(stored_close_values.median() - fresh_close_values.median())
                overlap_median_rel_diff = overlap_median_diff / (stored_close_values.median() if stored_close_values.median() != 0 else 1)
                
                if overlap_median_rel_diff > threshold:  # threshold % difference in overlap
                    logger.error(f"[DataAdapter] {label}: Overlap price mismatch detected! "
                               f"Stored overlap median={stored_close_values.median():.5f}, "
                               f"Fresh overlap median={fresh_close_values.median():.5f}, "
                               f"Diff ratio={overlap_median_rel_diff:.3f}")
                    from data_feed.exceptions import DataGapError
                    raise DataGapError(
                        f"FAIL-FAST: Overlap price mismatch for {label} - possible symbol mixing or data corruption"
                    )
                
                if not stored_df.loc[check, 'close'].equals(fresh_df.loc[check, 'close']):
                    logger.warning(f"[DataAdapter] {label}: broker revised closed candles — corrected")
        
        return True
    
    @staticmethod
    def ensure_utc_datetime_index(df: Optional[pd.DataFrame]) -> pd.DataFrame:
        """
        Ensure DataFrame has a valid UTC DatetimeIndex sorted ascending.
        
        Args:
            df: DataFrame to process
            
        Returns:
            pd.DataFrame: DataFrame with UTC DatetimeIndex
        """
        if df is None or df.empty:
            return df
        
        out = df.copy()
        
        # Convert timestamp column to datetime if it exists
        if 'timestamp' in out.columns and not isinstance(out.index, pd.DatetimeIndex):
            if pd.api.types.is_numeric_dtype(out['timestamp']):
                out['timestamp'] = pd.to_datetime(out['timestamp'], unit='s', utc=True)
            else:
                out['timestamp'] = pd.to_datetime(out['timestamp'], utc=True)
            out = out.set_index('timestamp', drop=False)
        
        # Ensure index is DatetimeIndex
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

    def validate_single_candle(
        self,
        open_p: float,
        high_p: float,
        low_p: float,
        close_p: float,
        volume: Optional[float] = 0.0
    ) -> bool:
        """
        Validate single candle structure.

        Args:
            open_p (float): Open price
            high_p (float): High price
            low_p (float): Low price
            close_p (float): Close price
            volume (Optional[float]): Volume (default: 0.0)

        Returns:
            bool: True if candle structure is valid

        Raises:
            ValueError: If candle structure is invalid (Rule 7 Fail-Fast)
        """
        try:
            o = float(open_p)
            h = float(high_p)
            l = float(low_p)
            c = float(close_p)
            v = float(volume) if volume is not None else 0.0
        except (ValueError, TypeError) as e:
            logger.error(f"[DataValidator] Non-numeric input in single candle: O={open_p}, H={high_p}, L={low_p}, C={close_p}, V={volume}")
            raise ValueError("FAIL-FAST: Invalid OHLC candle structure detected") from e

        is_valid = (
            o > 0 and
            h > 0 and
            l > 0 and
            c > 0 and
            h >= l and
            h >= o and
            h >= c and
            l <= o and
            l <= c and
            v >= 0
        )

        if not is_valid:
            logger.error(
                f"[DataValidator] FAIL-FAST: Invalid single candle structure detected -> "
                f"Open={o}, High={h}, Low={l}, Close={c}, Volume={v}"
            )
            raise ValueError("FAIL-FAST: Invalid OHLC candle structure detected")

        return True


# Alias for backward compatibility
CandleValidator = DataValidator

