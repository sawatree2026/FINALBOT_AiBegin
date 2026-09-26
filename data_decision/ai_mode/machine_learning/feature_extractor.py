"""
Feature Extractor Module for ATHENA ML Training System
======================================================
Location: ai_trainer_learning/feature_extractor.py
หน้าที่:
1. คำนวณและสกัด 17 ตัวแปรหลัก (Indicators & Price Action) จากแท่งเทียน
2. ป้องกัน Lookahead Bias 100% (คำนวณย้อนหลังเท่านั้น ห้ามใช้ข้อมูลอนาคต)
3. สอดคล้องกับโครงสร้างข้อมูล 17 ฟีเจอร์ของ LightGBM Engine & ML Dispatcher
"""

import logging
import traceback
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("FeatureExtractor")

ML_FEATURE_NAMES: List[str] = [
    # ── 1. Original Core Indicators ──
    "price_return_pct",     # 1. เปอร์เซ็นต์การขยับของราคา (close - open) / open * 1000
    "m5_bb_pos",            # 2. Position เทียบกรอบ Bollinger Bands (0.0-1.0)
    "bb_squeeze",           # 3. Bollinger Bands Squeeze Index (bb_width / sma20 * 100)
    "m5_rsi",               # 4. RSI (14) Wilder's Smoothing
    "rsi_divergence",       # 5. RSI Divergence Score (+1.0 Bullish, -1.0 Bearish, 0.0 ปกติ)
    "m5_stoch_k",           # 6. Stochastic %K (14, 3)
    "m5_stoch_d",           # 7. Stochastic %D (3)
    "m5_macd",              # 8. MACD Line (12, 26)
    "m5_macd_signal",       # 9. MACD Signal Line (9)
    "ema_cross_signal",     # 10. EMA9 vs EMA21 Spread normalized by ATR
    "m5_atr_norm",          # 11. ATR Normalized (ATR / close * 1000)
    "m5_lower_wick_ratio",  # 12. อัตราส่วนไส้เทียนล่าง
    "m5_upper_wick_ratio",  # 13. อัตราส่วนไส้เทียนบน
    "m5_pa_body_strength",  # 14. อัตราส่วนเนื้อเทียน
    "rejection",            # 15. ค่า Rejection (+1.0 ล่าง, -1.0 บน, 0.0 ปกติ)
    "m15_bias",             # 16. MTF Trend Bias / Alignment (-1.0 ถึง +1.0)
    "volume_ratio",         # 17. Volume Ratio เทียบ MA20

    # ── 2. Boss Directive: Volatility Filter ──
    "atr_ratio_20",         # 18. ATR ปัจจุบัน / SMA20 ของ ATR (แยก Sideway vs Breakout)

    # ── 3. Boss Directive: Market Structure ──
    "dist_to_resistance_20",# 19. ระยะห่างจากแนวต้านสูงสุด 20 แท่ง (normalized by ATR)
    "dist_to_support_20",   # 20. ระยะห่างจากแนวรับต่ำสุด 20 แท่ง (normalized by ATR)
    "hh_ll_score",          # 21. โครงสร้าง Higher High / Lower Low ใน 10 แท่ง (-1.0 ถึง +1.0)

    # ── 4. Boss Directive: Advanced Momentum Slopes ──
    "rsi_slope_3",          # 22. ความชันของ RSI ใน 3 แท่งล่าสุด (Rate of Change)
    "macd_hist_slope_3",    # 23. ความชันของ MACD Histogram ใน 3 แท่งล่าสุด

    # ── 5. Trend Strength ──
    "m5_adx",               # 24. ADX (14) วัดความแรงของเทรนด์ (0-100)

    # ── 6. Quant-Grade SNR Enhancement (Boss Directive) ──
    "snr_touch_score",      # 25. ตรวจจับการชนแนวรับต้าน (+1.0 ชนรับ, -1.0 ชนต้าน, 0.0 ปกติ)
    "m15_dist_to_res",      # 26. ระยะห่างจากแนวต้านใหญ่ M15 (normalized by ATR)
    "m15_dist_to_sup"       # 27. ระยะห่างจากแนวรับใหญ่ M15 (normalized by ATR)
]

# Alias for full backward compatibility
ML_17_FEATURE_NAMES = ML_FEATURE_NAMES


class FeatureExtractor:
    """Zero-Lookahead 17-Feature Extractor for Athena ML Models."""

    def __init__(self, warmup_period: int = 30):
        if not isinstance(warmup_period, int) or warmup_period < 14:
            raise ValueError(f"FAIL-FAST: warmup_period must be an integer >= 14, got {warmup_period}")
        self.warmup_period = warmup_period

    @staticmethod
    def _compute_rsi(close_series: pd.Series, period: int = 14) -> pd.Series:
        """คำนวณ RSI ด้วย Wilder's Smoothing (ป้องกัน Lookahead Bias)"""
        delta = close_series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0.0, 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def _compute_adx(high_s: pd.Series, low_s: pd.Series, close_s: pd.Series, period: int = 14) -> pd.Series:
        """คำนวณ ADX 14 แท่ง ด้วย Wilder's Smoothing (ป้องกัน Lookahead Bias)"""
        prev_close = close_s.shift(1)
        tr1 = high_s - low_s
        tr2 = (high_s - prev_close).abs()
        tr3 = (low_s - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = high_s - high_s.shift(1)
        down_move = low_s.shift(1) - low_s

        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high_s.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=low_s.index)

        alpha = 1.0 / period
        atr = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        plus_di = 100.0 * (plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr.replace(0.0, 1e-9))
        minus_di = 100.0 * (minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr.replace(0.0, 1e-9))

        dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, 1e-9))
        adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        return adx.clip(0.0, 100.0).fillna(20.0)

    @staticmethod
    def _compute_atr(high_s: pd.Series, low_s: pd.Series, close_s: pd.Series, period: int = 14) -> pd.Series:
        """คำนวณ ATR ด้วย Wilder's Smoothing (ป้องกัน Lookahead Bias)"""
        prev_close = close_s.shift(1)
        tr1 = high_s - low_s
        tr2 = (high_s - prev_close).abs()
        tr3 = (low_s - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        return atr.fillna(tr.rolling(period, min_periods=1).mean()).fillna(0.0005)

    def extract_features_df(
        self,
        df_m5: pd.DataFrame,
        df_m15: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        สกัด 17 Indicators & Price Action features จาก DataFrame แท่งเทียน
        """
        if not isinstance(df_m5, pd.DataFrame):
            raise TypeError(f"FAIL-FAST: df_m5 must be pd.DataFrame, got {type(df_m5)}")

        if len(df_m5) < self.warmup_period:
            raise ValueError(
                f"FAIL-FAST: Insufficient candle data for feature extraction. "
                f"Required >= {self.warmup_period}, got {len(df_m5)}"
            )

        close = df_m5["close"].astype(np.float64)
        open_p = df_m5["open"].astype(np.float64)
        high = df_m5["high"].astype(np.float64)
        low = df_m5["low"].astype(np.float64)
        volume = df_m5["volume"].astype(np.float64)

        # ── 1. Price Return Pct (แทนราคาปิดดิบ close) ────────────────────────
        price_return_pct = ((close - open_p) / open_p.replace(0.0, 1.0)) * 1000.0

        # ── 2. Bollinger Bands & Squeeze (20, 2) ─────────────────────────────
        sma20 = close.rolling(window=20, min_periods=5).mean()
        std20 = close.rolling(window=20, min_periods=5).std(ddof=0).fillna(1e-6)
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)
        bb_range = (bb_upper - bb_lower).replace(0.0, 1e-9)
        bb_pos = ((close - bb_lower) / bb_range).clip(0.0, 1.0)
        bb_squeeze = ((bb_upper - bb_lower) / sma20.replace(0.0, 1.0)) * 100.0

        # ── 3. RSI (14) & RSI Divergence ─────────────────────────────────────
        rsi = self._compute_rsi(close, period=14)
        price_slope_5 = close.diff(5)
        rsi_slope_5 = rsi.diff(5)
        rsi_div = pd.Series(0.0, index=df_m5.index)
        # Bullish Divergence: Price making lower lows, RSI making higher lows
        bull_div = (price_slope_5 < 0) & (rsi_slope_5 > 2.0) & (rsi < 45.0)
        # Bearish Divergence: Price making higher highs, RSI making lower highs
        bear_div = (price_slope_5 > 0) & (rsi_slope_5 < -2.0) & (rsi > 55.0)
        rsi_div = rsi_div.mask(bull_div, 1.0)
        rsi_div = rsi_div.mask(bear_div, -1.0)

        # ── 4. Stochastic (%K, %D) ───────────────────────────────────────────
        low_14 = low.rolling(window=14, min_periods=5).min()
        high_14 = high.rolling(window=14, min_periods=5).max()
        stoch_denom = (high_14 - low_14).replace(0.0, 1e-9)
        stoch_k_raw = ((close - low_14) / stoch_denom) * 100.0
        stoch_k = stoch_k_raw.rolling(window=3, min_periods=1).mean().clip(0.0, 100.0)
        stoch_d = stoch_k.rolling(window=3, min_periods=1).mean().clip(0.0, 100.0)

        # ── 5. MACD (12, 26, 9) ──────────────────────────────────────────────
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()

        # ── 6. ATR & Normalized ATR ──────────────────────────────────────────
        atr = self._compute_atr(high, low, close, period=14)
        atr_norm = (atr / close.replace(0.0, 1.0)) * 1000.0

        # ── 7. EMA Cross Spread Normalized ───────────────────────────────────
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        ema_cross_signal = ((ema9 - ema21) / atr.replace(0.0, 1e-9)).clip(-3.0, 3.0)

        # ── 8. Price Action Wicks & Rejection ─────────────────────────────────
        candle_range = (high - low).replace(0.0, 1e-9)
        upper_wick = (high - np.maximum(open_p, close)) / candle_range
        lower_wick = (np.minimum(open_p, close) - low) / candle_range
        body_strength = (close - open_p).abs() / candle_range

        rejection = pd.Series(0.0, index=df_m5.index)
        is_bull_rejection = (lower_wick >= 0.40) & (close >= open_p)
        is_bear_rejection = (upper_wick >= 0.40) & (close <= open_p)
        rejection = rejection.mask(is_bull_rejection, 1.0)
        rejection = rejection.mask(is_bear_rejection, -1.0)

        # ── 9. Market Structure & Prior Pivots High/Low 20 ───────────────────
        high_20 = high.shift(1).rolling(window=20, min_periods=1).max().fillna(high)
        low_20 = low.shift(1).rolling(window=20, min_periods=1).min().fillna(low)
        dist_to_resistance_20 = ((high_20 - close) / atr.replace(0.0, 1e-9)).clip(-5.0, 10.0).fillna(0.0)
        dist_to_support_20 = ((close - low_20) / atr.replace(0.0, 1e-9)).clip(-5.0, 10.0).fillna(0.0)

        # ── 10. Quant SNR Direct Touch Trigger (Boss Directive) ──────────────
        is_sup_touch = low <= (low_20 + 0.15 * atr)
        is_res_touch = high >= (high_20 - 0.15 * atr)
        snr_touch_score = pd.Series(0.0, index=df_m5.index)
        snr_touch_score[is_sup_touch] = 1.0
        snr_touch_score[is_res_touch] = -1.0
        snr_touch_score[is_sup_touch & is_res_touch] = 0.0

        # ── 11. Multi-Timeframe (MTF) Alignment & Large SNR from M15 ─────────
        trend_slope = ((ema9 - ema21) / ema21.replace(0.0, 1e-9)) * 1000.0
        m15_bias = trend_slope.clip(-2.0, 2.0)
        m15_dist_to_res = dist_to_resistance_20.copy()
        m15_dist_to_sup = dist_to_support_20.copy()

        if df_m15 is not None and not df_m15.empty and len(df_m15) >= 20:
            m15_close = df_m15["close"].astype(np.float64)
            m15_high = df_m15["high"].astype(np.float64)
            m15_low = df_m15["low"].astype(np.float64)
            m15_ema9 = m15_close.ewm(span=9, adjust=False).mean()
            m15_ema21 = m15_close.ewm(span=21, adjust=False).mean()
            m15_diff = (m15_ema9 - m15_ema21) / m15_ema21.replace(0.0, 1e-9)

            m15_res_20 = m15_high.shift(1).rolling(window=20, min_periods=1).max().fillna(m15_high)
            m15_sup_20 = m15_low.shift(1).rolling(window=20, min_periods=1).min().fillna(m15_low)

            if "timestamp" in df_m15.columns and "timestamp" in df_m5.columns:
                m15_ts = pd.to_datetime(df_m15["timestamp"], utc=True)
                m5_ts = pd.to_datetime(df_m5["timestamp"], utc=True)
                m15_temp = pd.DataFrame({
                    "timestamp": m15_ts + pd.Timedelta(minutes=15),
                    "m15_slope": m15_diff * 1000.0,
                    "m15_res_20": m15_res_20,
                    "m15_sup_20": m15_sup_20
                })
                merged = pd.merge_asof(
                    pd.DataFrame({"timestamp": m5_ts}),
                    m15_temp,
                    on="timestamp",
                    direction="backward"
                )
                m15_bias = merged["m15_slope"].fillna(trend_slope).clip(-2.0, 2.0)
                m15_res_series = merged["m15_res_20"].fillna(high_20)
                m15_sup_series = merged["m15_sup_20"].fillna(low_20)
                m15_dist_to_res = ((m15_res_series - close) / atr.replace(0.0, 1e-9)).clip(-5.0, 15.0).fillna(dist_to_resistance_20)
                m15_dist_to_sup = ((close - m15_sup_series) / atr.replace(0.0, 1e-9)).clip(-5.0, 15.0).fillna(dist_to_support_20)

        # ── 12. Volume Ratio ─────────────────────────────────────────────────
        vol_ma20 = volume.rolling(window=20, min_periods=1).mean().replace(0.0, 1.0)
        volume_ratio = (volume / vol_ma20).fillna(1.0).clip(0.0, 10.0)

        # ── 13. Boss Directive: Volatility Filter (ATR Ratio 20) ─────────────
        atr_ma20 = atr.rolling(window=20, min_periods=1).mean().replace(0.0, 1e-9)
        atr_ratio_20 = (atr / atr_ma20).fillna(1.0).clip(0.2, 5.0)

        # ── 14. Higher High / Lower Low Score ────────────────────────────────
        hh = (high > high.shift(1)).rolling(window=10, min_periods=1).sum() / 10.0
        ll = (low < low.shift(1)).rolling(window=10, min_periods=1).sum() / 10.0
        hh_ll_score = (hh - ll).clip(-1.0, 1.0).fillna(0.0)

        # ── 15. Advanced Momentum Slopes (RSI & MACD Slopes) ─────────────────
        rsi_slope_3 = ((rsi - rsi.shift(3)) / 3.0).fillna(0.0).clip(-30.0, 30.0)
        macd_hist = macd_line - macd_signal
        macd_hist_slope_3 = (((macd_hist - macd_hist.shift(3)) / 3.0) / atr.replace(0.0, 1e-9)).fillna(0.0).clip(-5.0, 5.0)

        # ── 16. ADX (14) Trend Strength ──────────────────────────────────────
        m5_adx = self._compute_adx(high, low, close, period=14)

        # ── Build Final Feature DataFrame ────────────────────────────────────
        feat_dict: Dict[str, pd.Series] = {
            "price_return_pct": price_return_pct,
            "m5_bb_pos": bb_pos,
            "bb_squeeze": bb_squeeze,
            "m5_rsi": rsi,
            "rsi_divergence": rsi_div,
            "m5_stoch_k": stoch_k,
            "m5_stoch_d": stoch_d,
            "m5_macd": macd_line,
            "m5_macd_signal": macd_signal,
            "ema_cross_signal": ema_cross_signal,
            "m5_atr_norm": atr_norm,
            "m5_lower_wick_ratio": lower_wick,
            "m5_upper_wick_ratio": upper_wick,
            "m5_pa_body_strength": body_strength,
            "rejection": rejection,
            "m15_bias": m15_bias,
            "volume_ratio": volume_ratio,
            "atr_ratio_20": atr_ratio_20,
            "dist_to_resistance_20": dist_to_resistance_20,
            "dist_to_support_20": dist_to_support_20,
            "hh_ll_score": hh_ll_score,
            "rsi_slope_3": rsi_slope_3,
            "macd_hist_slope_3": macd_hist_slope_3,
            "m5_adx": m5_adx,
            "snr_touch_score": snr_touch_score,
            "m15_dist_to_res": m15_dist_to_res,
            "m15_dist_to_sup": m15_dist_to_sup
        }

        feat_df = pd.DataFrame(feat_dict, index=df_m5.index)

        for name in ML_FEATURE_NAMES:
            if name not in feat_df.columns:
                raise ValueError(f"FAIL-FAST: Missing feature column {name} in extracted features")

        return feat_df

    def extract_features_matrix(
        self,
        df_m5: pd.DataFrame,
        df_m15: Optional[pd.DataFrame] = None
    ) -> Tuple[np.ndarray, List[str], pd.DataFrame]:
        """
        แปลงข้อมูลเป็น Matrix NumPy (X) พร้อมรายชื่อฟีเจอร์ 17 ตัว
        """
        feat_df = self.extract_features_df(df_m5=df_m5, df_m15=df_m15)
        valid_df = feat_df.iloc[self.warmup_period:].copy()
        X = valid_df[ML_17_FEATURE_NAMES].values.astype(np.float64)
        return X, ML_17_FEATURE_NAMES, valid_df
