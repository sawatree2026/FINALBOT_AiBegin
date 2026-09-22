"""
indicator_store.py
------------------
Single Source of Truth (SSOT) สำหรับ FINALBOT
- คำนวณ Raw Indicators (Layer 1) ครั้งเดียว (รวม ADX, Volume Ratio, Slope)
- ให้ Engine (Layer 2) และ Classifier (Layer 3) ใช้งาน
- รองรับการทำงานแบบ Parallel
"""

import pandas as pd
import numpy as np
import threading
import copy
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import logging

from data_evaluate.orchestration.indicator_store.core_indicators import CoreIndicators
from data_evaluate.orchestration.indicator_store.structural_metrics import StructuralMetrics

# ---------- Logging Setup ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------- Configuration ----------
class Config:
    ROUND_DECIMALS = 6
    ADX_PERIOD = 14
    VOLUME_MA_PERIOD = 20
    SLOPE_PERIOD = 10  # ใช้ 10 แท่งล่าสุดสำหรับ Linear Regression

# ---------- Core Class ----------
class IndicatorStore:
    """
    จัดเก็บ Indicator เฉพาะ Layer 1 สำหรับทุกคู่เงิน
    - Layer 1: Raw Indicators (คำนวณจาก OHLCV โดยตรง)
    """

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ========================
    # LAYER 1: RAW INDICATORS (คำนวณจาก OHLCV)
    # ========================
    @staticmethod
    def calculate_raw_indicators(df_m1: pd.DataFrame, df_m5: pd.DataFrame, df_m15: Optional[pd.DataFrame] = None, forming_data: Optional[Dict[str, Any]] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        คำนวณ Indicator ดิบ (Layer 1) จาก DataFrame M1, M5 และ M15
        - ใช้ Pandas Vectorization (เร็วมาก)
        - ส่งคืน dict ที่มีเฉพาะ 'm5', 'm1', 'ohlcv'
        """
        # ------------------------------------------------------------
        # 0. Warm-up Candle Lookback Check (Fail-Fast)
        # M5: minimum 200 candles (requires EMA200)
        # M1: minimum 100 candles (only EMA20 needed)
        # M15: minimum 100 candles (only EMA20 needed)
        # ------------------------------------------------------------
        if df_m1 is None or df_m1.empty or len(df_m1) < 250:
            raise ValueError("FAIL-FAST: Insufficient M1 warm-up candles (minimum 250 required)")
        if df_m5 is None or df_m5.empty or len(df_m5) < 250:
            raise ValueError("FAIL-FAST: Insufficient M5 warm-up candles (minimum 250 required)")
        if df_m15 is None or df_m15.empty or len(df_m15) < 250:
            raise ValueError("FAIL-FAST: Insufficient M15 warm-up candles (minimum 250 required)")

        # ------------------------------------------------------------
        # 1. M5 Indicators
        # ------------------------------------------------------------
        m5 = {}
        close_m5 = df_m5['close']
        high_m5 = df_m5['high']
        low_m5 = df_m5['low']
        open_m5 = df_m5['open']
        volume_m5 = df_m5['volume']

        # EMA
        m5.update(CoreIndicators.calculate_ema(close_m5, [5, 10, 20, 50, 100, 200], Config.ROUND_DECIMALS))
        
        # M5 Bias
        m5['bias'] = 'BULLISH' if close_m5.iloc[-1] > m5['ema20'] else 'BEARISH'

        # Bollinger Bands (20, 2)
        m5.update(CoreIndicators.calculate_bb(close_m5, 20, Config.ROUND_DECIMALS, require_100=True))

        # RSI (14)
        m5['rsi14'] = CoreIndicators.calc_rsi(close_m5, 14)

        # MACD (12, 26, 9)
        m5.update(CoreIndicators.calculate_macd(close_m5, Config.ROUND_DECIMALS, include_hist=True))

        # Stochastic (14, 3, 3)
        m5.update(CoreIndicators.calculate_stochastic(close_m5, high_m5, low_m5))

        # ATR (14)
        m5.update(StructuralMetrics.calculate_atr(high_m5, low_m5, close_m5, Config.ROUND_DECIMALS, extended=True))

        # ADX (14)
        m5.update(StructuralMetrics.calc_adx(high_m5, low_m5, close_m5, Config.ADX_PERIOD))

        # Volume Metrics
        m5.update(StructuralMetrics.calculate_volume_metrics(volume_m5, Config.VOLUME_MA_PERIOD, extended=True))

        # ROC (10 periods)
        if len(close_m5) < 10:
            raise ValueError("Not enough data to calculate ROC")
        m5['roc'] = round(((close_m5.iloc[-1] / (close_m5.iloc[-10] + 1e-9)) - 1) * 100, 4)

        # ================================================================
        # LINEAR REGRESSION SLOPE
        # ================================================================
        m5['slope_10'] = round(StructuralMetrics.calc_slope(close_m5, 10), Config.ROUND_DECIMALS)

        # ================================================================
        # FLOOR PIVOT POINTS (UNIFIED METHODOLOGY)
        # All pivot and S/R levels come from the same Floor Pivot calculation
        # This ensures consistency between pivot and support/resistance
        # ================================================================
        if len(df_m5) < 1:
            raise ValueError("FAIL-FAST: Insufficient M5 candles for Pivot Point calculation (minimum 1 required)")
        
        # Use the last completed candle (iloc[-1] is the most recent completed candle because forming candle is already dropped by data_feed)
        completed_high = high_m5.iloc[-1]
        completed_low = low_m5.iloc[-1]
        completed_close = close_m5.iloc[-1]
        
        # Floor Pivot: P = (H + L + C) / 3
        pivot = (completed_high + completed_low + completed_close) / 3
        m5['pivot'] = round(pivot, Config.ROUND_DECIMALS)
        
        # Floor Pivot Support & Resistance Levels (all derived from same pivot)
        # R1 = (2 * P) - L
        m5['r1'] = round((2 * pivot) - completed_low, Config.ROUND_DECIMALS)
        # S1 = (2 * P) - H
        m5['s1'] = round((2 * pivot) - completed_high, Config.ROUND_DECIMALS)
        
        # PRIMARY SUPPORT & RESISTANCE (using Floor Pivot methodology)
        # Use S1 as primary support and R1 as primary resistance
        # These are the most relevant levels from the Floor Pivot system
        m5['support'] = m5['s1']  # S1 = (2 * P) - H
        m5['resistance'] = m5['r1']  # R1 = (2 * P) - L

        # Box Metrics
        m5.update(StructuralMetrics.calculate_box_metrics(high_m5, low_m5, m5['atr14']))

        # Save actual OHLCV values in m5 dictionary for orchestrator to consume
        m5['open'] = round(open_m5.iloc[-1], Config.ROUND_DECIMALS)
        m5['high'] = round(high_m5.iloc[-1], Config.ROUND_DECIMALS)
        m5['low'] = round(low_m5.iloc[-1], Config.ROUND_DECIMALS)
        m5['close'] = round(close_m5.iloc[-1], Config.ROUND_DECIMALS)

        # ------------------------------------------------------------
        # 2. M1 Indicators
        # ------------------------------------------------------------
        m1 = {}
        close_m1 = df_m1['close']
        high_m1 = df_m1['high']
        low_m1 = df_m1['low']
        open_m1 = df_m1['open']
        volume_m1 = df_m1['volume']

        # EMA (5, 20, 50 for M1)
        m1.update(CoreIndicators.calculate_ema(close_m1, [5, 20, 50], Config.ROUND_DECIMALS))
        
        # M1 Bias
        m1['bias'] = 'BULLISH' if close_m1.iloc[-1] > m1['ema20'] else 'BEARISH'

        # RSI (14)
        m1['rsi14'] = CoreIndicators.calc_rsi(close_m1, 14)

        # MACD (12, 26, 9)
        m1.update(CoreIndicators.calculate_macd(close_m1, Config.ROUND_DECIMALS, include_hist=True))

        # Stochastic (14, 3, 3)
        m1.update(CoreIndicators.calculate_stochastic(close_m1, high_m1, low_m1))

        # ATR (14) - Removed as not used by any engine
        # m1.update(StructuralMetrics.calculate_atr(high_m1, low_m1, close_m1, Config.ADX_PERIOD, Config.ROUND_DECIMALS))

        # ADX (14) - Removed as not used by any engine
        # m1.update(StructuralMetrics.calc_adx(high_m1, low_m1, close_m1, Config.ADX_PERIOD))

        # Volume Metrics (M1 - extended) - Removed as not used by any engine
        # m1.update(StructuralMetrics.calculate_volume_metrics(volume_m1, Config.VOLUME_MA_PERIOD, extended=True))

        # ROC (10 periods) - Removed as not used by any engine
        # if len(close_m1) < 10:
        #     raise ValueError("Not enough data to calculate ROC")
        # m1['roc'] = round(((close_m1.iloc[-1] / (close_m1.iloc[-10] + 1e-9)) - 1) * 100, 4)

        # Slope - Removed as not used by any engine
        # m1['slope_10'] = round(StructuralMetrics.calc_slope(close_m1, 10), Config.ROUND_DECIMALS)
        # m1['slope_20'] = round(StructuralMetrics.calc_slope(close_m1, 20), Config.ROUND_DECIMALS)
        # m1['slope_50'] = round(StructuralMetrics.calc_slope(close_m1, 50), Config.ROUND_DECIMALS)

        
        # Save actual OHLCV values in m1 dictionary
        m1['open'] = round(open_m1.iloc[-1], Config.ROUND_DECIMALS)
        m1['high'] = round(high_m1.iloc[-1], Config.ROUND_DECIMALS)
        m1['low'] = round(low_m1.iloc[-1], Config.ROUND_DECIMALS)
        m1['close'] = round(close_m1.iloc[-1], Config.ROUND_DECIMALS)

        # ------------------------------------------------------------
        # 3. Meta (OHLCV for reference)
        # ------------------------------------------------------------
        ohlcv = {
            'm5_open': round(open_m5.iloc[-1], Config.ROUND_DECIMALS),
            'm5_high': round(high_m5.iloc[-1], Config.ROUND_DECIMALS),
            'm5_low': round(low_m5.iloc[-1], Config.ROUND_DECIMALS),
            'm5_close': round(close_m5.iloc[-1], Config.ROUND_DECIMALS),
            'm5_volume': int(volume_m5.iloc[-1]) if not pd.isna(volume_m5.iloc[-1]) else 0,
            'm1_open': round(open_m1.iloc[-1], Config.ROUND_DECIMALS),
            'm1_high': round(high_m1.iloc[-1], Config.ROUND_DECIMALS),
            'm1_low': round(low_m1.iloc[-1], Config.ROUND_DECIMALS),
            'm1_close': round(close_m1.iloc[-1], Config.ROUND_DECIMALS),
            'm1_volume': int(volume_m1.iloc[-1]) if not pd.isna(volume_m1.iloc[-1]) else 0,
            'm1_age': int(df_m1['age'].iloc[-1]) if 'age' in df_m1 else 0,
            'm1_quality': str(df_m1['quality'].iloc[-1]) if 'quality' in df_m1 else 'STALE',
            'm5_age': int(df_m5['age'].iloc[-1]) if 'age' in df_m5 else 0,
            'm5_quality': str(df_m5['quality'].iloc[-1]) if 'quality' in df_m5 else 'STALE'
        }

        # ------------------------------------------------------------
        # 4. M15 Indicators (if provided)
        # ------------------------------------------------------------
        m15 = {}
        if df_m15 is not None and not df_m15.empty:
            close_m15 = df_m15['close']
            high_m15 = df_m15['high']
            low_m15 = df_m15['low']
            open_m15 = df_m15['open']
            volume_m15 = df_m15['volume']

            # EMA - Only calculate periods actually used by engines (EMA20, EMA50)
            m15.update(CoreIndicators.calculate_ema(close_m15, [20, 50], Config.ROUND_DECIMALS))
            
            # M15 Bias
            m15['bias'] = 'BULLISH' if close_m15.iloc[-1] > m15['ema20'] else 'BEARISH'

            # Bollinger Bands (20, 2) - Removed as not used by any engine
            # m15.update(CoreIndicators.calculate_bb(close_m15, 20, Config.ROUND_DECIMALS, require_100=True))

            # RSI (14 only - rsi7 not used by any engine)
            m15['rsi14'] = CoreIndicators.calc_rsi(close_m15, 14)

            # MACD (12, 26, 9) - Removed as not used by any engine
            # m15.update(CoreIndicators.calculate_macd(close_m15, Config.ROUND_DECIMALS, include_hist=True))

            # Stochastic (14, 3, 3) - Removed as not used by any engine
            # m15.update(CoreIndicators.calculate_stochastic(close_m15, high_m15, low_m15))

            # ATR (14) - Removed as not used by any engine
            # m15.update(StructuralMetrics.calculate_atr(high_m15, low_m15, close_m15, Config.ADX_PERIOD, Config.ROUND_DECIMALS))

            # ADX (14) - Removed as not used by any engine
            # m15.update(StructuralMetrics.calc_adx(high_m15, low_m15, close_m15, Config.ADX_PERIOD))

            # Volume Metrics - Removed as not used by any engine
            # m15.update(StructuralMetrics.calculate_volume_metrics(volume_m15, Config.VOLUME_MA_PERIOD, extended=True))

            # ROC (10 periods) - Removed as not used by any engine
            # if len(close_m15) < 10:
            #     raise ValueError("Not enough data to calculate ROC")
            # m15['roc'] = round(((close_m15.iloc[-1] / (close_m15.iloc[-10] + 1e-9)) - 1) * 100, 4)

            # Slope - Removed as not used by any engine
            # m15['slope_10'] = round(StructuralMetrics.calc_slope(close_m15, 10), Config.ROUND_DECIMALS)
            # m15['slope_20'] = round(StructuralMetrics.calc_slope(close_m15, 20), Config.ROUND_DECIMALS)
            # m15['slope_50'] = round(StructuralMetrics.calc_slope(close_m15, 50), Config.ROUND_DECIMALS)

            # M15 Pivot (Floor Pivot) - Removed as not used by any engine
            # last_candle_m15 = df_m15.iloc[-1]
            # pivot_m15 = (last_candle_m15['high'] + last_candle_m15['low'] + last_candle_m15['close']) / 3
            # m15['pivot'] = round(pivot_m15, Config.ROUND_DECIMALS)
            # m15['r1'] = round((2 * pivot_m15) - last_candle_m15['low'], Config.ROUND_DECIMALS)
            # m15['s1'] = round((2 * pivot_m15) - last_candle_m15['high'], Config.ROUND_DECIMALS)
            # m15['support'] = m15['s1']
            # m15['resistance'] = m15['r1']

            # Save actual OHLCV values in m15 dictionary - Removed as not used by any engine
            # m15['open'] = round(open_m15.iloc[-1], Config.ROUND_DECIMALS)
            # m15['high'] = round(high_m15.iloc[-1], Config.ROUND_DECIMALS)
            # m15['low'] = round(low_m15.iloc[-1], Config.ROUND_DECIMALS)
            # m15['close'] = round(close_m15.iloc[-1], Config.ROUND_DECIMALS)

            # Update ohlcv with M15 data - Removed as not used by any engine
            # ohlcv['m15_open'] = round(open_m15.iloc[-1], Config.ROUND_DECIMALS)
            # ohlcv['m15_high'] = round(high_m15.iloc[-1], Config.ROUND_DECIMALS)
            # ohlcv['m15_low'] = round(low_m15.iloc[-1], Config.ROUND_DECIMALS)
            # ohlcv['m15_close'] = round(close_m15.iloc[-1], Config.ROUND_DECIMALS)
            # ohlcv['m15_volume'] = int(volume_m15.iloc[-1]) if not pd.isna(volume_m15.iloc[-1]) else 0

        # ------------------------------------------------------------
        # 5. Build Layer Data
        # ------------------------------------------------------------
        layer_data = {
            'm5': m5,
            'm1': m1,
            'm15': m15 if m15 else None,
            'ohlcv': ohlcv,
            'meta': {
                'symbol': symbol,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'm5_candles': len(df_m5),
                'm1_candles': len(df_m1),
                'm15_candles': len(df_m15) if df_m15 is not None else 0,
            }
        }

        return layer_data

    def set_raw(self, symbol: str, raw_data: Dict[str, Any]):
        """บันทึก Raw Indicators ลง Store"""
        with self._lock:
            if symbol not in self._data:
                self._data[symbol] = {}
            self._data[symbol]['raw'] = raw_data
            self._data[symbol]['updated_at'] = datetime.now(timezone.utc).isoformat()

    def get_raw(self, symbol: str) -> Optional[Dict[str, Any]]:
        """ดึง Raw Indicators ของ symbol"""
        with self._lock:
            if symbol not in self._data:
                return None
            return copy.deepcopy(self._data[symbol]['raw'])

    def get_full_snapshot(self, symbol: str) -> Dict[str, Any]:
        """ดึงข้อมูลทั้งหมดของ symbol หนึ่ง"""
        with self._lock:
            return copy.deepcopy(self._data[symbol])

    def get_all_symbols(self) -> List[str]:
        """รายชื่อคู่เงินทั้งหมดที่มีข้อมูล"""
        with self._lock:
            return list(self._data.keys())

    def get_payload(self, symbol: str) -> Dict[str, Any]:
        """คืนค่า Raw Indicator ({'m5': ..., 'm1': ..., 'ohlcv': ...})"""
        snapshot = self.get_full_snapshot(symbol)
        return snapshot['raw']

    # ========================
    # PROCESS PAIR (หลัก)
    # ========================
    def process_pair(self, symbol: str, df_m1: pd.DataFrame, df_m5: pd.DataFrame, df_m15: Optional[pd.DataFrame] = None, forming_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        ขั้นตอนหลัก: คำนวณ Layer 1 (Raw Indicators) จาก DataFrame
        """
        logger.debug(f"Processing {symbol} ...")
        
        # คำนวณ Raw Indicators
        raw = self.calculate_raw_indicators(df_m1, df_m5, df_m15, forming_data, symbol=symbol)
        
        # บันทึกลง Store
        self.set_raw(symbol, raw)
        
        return raw

    def calculate_all(self, symbol: str, candles_dict: Dict[str, pd.DataFrame], session: str = "asian", forming_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Backward compatibility wrapper"""
        df_m1 = candles_dict['M1']
        df_m5 = candles_dict['M5']
        df_m15 = candles_dict['M15']
        
        if df_m1 is None or df_m5 is None or df_m1.empty or df_m5.empty:
            logger.error(f"Missing M1 or M5 data for {symbol} in calculate_all")
            raise Exception(f"Missing M1 or M5 data for {symbol}")

        return self.process_pair(symbol, df_m1, df_m5, df_m15, forming_data)

    # ========================
    # CLEANUP
    # ========================
    def clear_all(self):
        """ล้างข้อมูลทั้งหมด"""
        with self._lock:
            self._data.clear()
        logger.debug("IndicatorStore cleared")

    def clear_symbol(self, symbol: str):
        """ล้างข้อมูลเฉพาะคู่"""
        with self._lock:
            if symbol in self._data:
                del self._data[symbol]

# Global Singleton Instance สำหรับให้ไฟล์อื่น import ไปใช้
store = IndicatorStore()

# =================================================================
# ตัวอย่างการใช้งาน
# =================================================================
def run_parallel_processing(store: IndicatorStore, symbols_data: Dict[str, Tuple[pd.DataFrame, pd.DataFrame]]):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    results = {}
    start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=len(symbols_data)) as executor:
        future_to_symbol = {
            executor.submit(store.process_pair, symbol, df_m1, df_m5): symbol
            for symbol, (df_m1, df_m5) in symbols_data.items()
        }
        
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                raw = future.result()
                results[symbol] = raw
                logger.info(f"✅ {symbol} processed in {time.perf_counter() - start:.3f}s")
            except Exception as e:
                raise

    elapsed = time.perf_counter() - start
    logger.info(f"✨ All pairs processed in {elapsed:.3f} seconds")
    return results

if __name__ == "__main__":
    from datetime import datetime
    print("INDICATOR STORE - REFACTORED (PURE LAYER 1)")
