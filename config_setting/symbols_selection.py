"""
Native Symbol Selection Engine for FINALBOT (symbols_selection.py)
========================================================================================
ระบบประเมิน คัดกรอง และจัดอันดับคู่เงินน่าเทรดเชิงปริมาณ 100 คะแนนเต็ม
(7 Skills + 4 Edges + S/R Room to Run + Payout Guard)
สำหรับบอทเทรดหลัก (runner.py) และการรัน Standalone

ข้อกำหนดทางเทคนิค:
1. แหล่งคู่เงิน: โหลด SET_A (13 คู่) และ SET_B (21 คู่) จาก config_setting/symbols_user.json
2. คอนฟิกหลัก: โหลด min_payout และ max_symbols จาก config_setting/settings.json
3. ดึงแท่งเทียน: PURE IN-MEMORY (RAM Only) ไม่บันทึก CSV ไม่เขียนไฟล์ชั่วคราวลง SSD ระหว่างสแกน
4. ผลลัพธ์: Atomic Write บันทึก Top picks ลง config_setting/symbols.json (Single Source of Truth)
"""

import os
import sys
import json
import time
import math
import logging
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple, Union

# Ensure UTF-8 output safely for Windows CMD / PowerShell
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("symbols_selection")


# ==============================================================================
# SECTION 1: สภาพคล่องและช่วงเวลาตลาดโลก (Skill: liquidity-analysis - 10 คะแนน)
# ==============================================================================
MARKET_SESSIONS_UTC = {
    "SYDNEY":   {"start": 21, "end": 6,  "currencies": ["AUD", "NZD"]},
    "TOKYO":    {"start": 0,  "end": 9,  "currencies": ["JPY", "AUD", "NZD", "SGD", "HKD", "CNY"]},
    "LONDON":   {"start": 7,  "end": 16, "currencies": ["EUR", "GBP", "CHF"]},
    "NEW_YORK": {"start": 12, "end": 21, "currencies": ["USD", "CAD"]}
}


def get_active_sessions(dt_utc: Optional[datetime] = None) -> List[str]:
    """คำนวณตลาดโลกที่กำลังเปิดทำการ ณ เวลา UTC ปัจจุบัน"""
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
    hour = dt_utc.hour
    active = []
    for session_name, info in MARKET_SESSIONS_UTC.items():
        s, e = info["start"], info["end"]
        if s < e:
            if s <= hour < e:
                active.append(session_name)
        else:
            if hour >= s or hour < e:
                active.append(session_name)
    return active


def analyze_session_liquidity(symbol: str, dt_utc: Optional[datetime] = None) -> Dict[str, Any]:
    """วิเคราะห์ระดับสภาพคล่องตามเวลาทำการของตลาดโลกและ OTC (Skill: liquidity-analysis)"""
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
        
    clean_sym = symbol.upper()
    is_otc = clean_sym.endswith("-OTC")
    base_sym = clean_sym.replace("-OTC", "").replace("-OP", "")
    active_sessions = get_active_sessions(dt_utc)
    
    if is_otc:
        return {
            "is_otc": True,
            "score": 10.0,
            "liquidity_level": "HIGH",
            "liquidity_tag": "🟢 สภาพคล่อง OTC สม่ำเสมอ",
            "description": "ตลาด OTC มีสภาพคล่องสังเคราะห์ตลอด 24 ชม."
        }
        
    curr_a = base_sym[:3] if len(base_sym) >= 3 else ""
    curr_b = base_sym[3:6] if len(base_sym) >= 6 else ""
    open_currs = set()
    for s_name in active_sessions:
        for c in MARKET_SESSIONS_UTC.get(s_name, {}).get("currencies", []):
            if c in (curr_a, curr_b):
                open_currs.add(c)
                
    has_overlap = ("LONDON" in active_sessions and "NEW_YORK" in active_sessions)
    if len(open_currs) >= 2 or (has_overlap and len(open_currs) >= 1):
        score = 10.0
        level = "HIGH"
        tag = "🟢 สภาพคล่องสูง (Peak Session)"
        desc = f"ตลาดเปิดพร้อมกัน ({', '.join(open_currs)}) ใน {', '.join(active_sessions)}"
    elif len(open_currs) == 1:
        score = 7.0
        level = "MEDIUM"
        tag = "🟡 สภาพคล่องปานกลาง (Single Open)"
        desc = f"ตลาดเปิด 1 สกุล ({', '.join(open_currs)}) ใน {', '.join(active_sessions)}"
    else:
        score = 3.0
        level = "LOW"
        tag = "⚪ สภาพคล่องต่ำ (Off-Hours)"
        desc = f"อยู่นอกเวลาทำการหลัก ({curr_a}/{curr_b})"
        
    return {
        "is_otc": False,
        "score": score,
        "liquidity_level": level,
        "liquidity_tag": tag,
        "description": desc
    }


# ==============================================================================
# SECTION 2: วิเคราะห์ความผันผวน (Skills: volatility-modeling, pandas-ta - 25 คะแนน)
# ==============================================================================
def analyze_volatility_metrics(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    คำนวณ Garman-Klass Volatility, Parkinson Volatility, และ Normalized ATR%
    (Skills: volatility-modeling & pandas-ta)
    """
    if not candles or len(candles) < 5:
        return {
            "score": 0.0,
            "regime": "NO_DATA",
            "gk_vol": 0.0,
            "parkinson_vol": 0.0,
            "atr_pct": 0.0,
            "status_tag": "⚪ ไม่มีข้อมูล"
        }

    gk_terms = []
    parkinson_terms = []
    trs = []
    prev_close = None

    for c in candles:
        o = float(c.get("open", 0))
        h = float(c.get("max", c.get("high", 0)))
        l = float(c.get("min", c.get("low", 0)))
        cl = float(c.get("close", 0))

        if h <= 0 or l <= 0 or o <= 0 or cl <= 0:
            continue

        # Garman-Klass Volatility Term
        u = math.log(max(h / max(l, 1e-6), 1.000001))
        v = math.log(max(cl / max(o, 1e-6), 1e-6))
        gk_term = 0.5 * (u ** 2) - (2.0 * math.log(2.0) - 1.0) * (v ** 2)
        gk_terms.append(gk_term)

        # Parkinson Range Volatility Term: (ln(H/L))^2 / (4 * ln(2))
        p_term = (u ** 2) / (4.0 * math.log(2.0))
        parkinson_terms.append(p_term)

        # True Range
        tr = h - l
        if prev_close is not None:
            tr = max(tr, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = cl

    if not gk_terms:
        return {
            "score": 0.0,
            "regime": "DEAD",
            "gk_vol": 0.0,
            "parkinson_vol": 0.0,
            "atr_pct": 0.0,
            "status_tag": "⚪ กราฟตาย"
        }

    gk_vol = math.sqrt(max(sum(gk_terms) / len(gk_terms), 0.0))
    parkinson_vol = math.sqrt(max(sum(parkinson_terms) / len(parkinson_terms), 0.0)) if parkinson_terms else 0.0
    last_close = float(candles[-1].get("close", 0.0))
    if last_close <= 0.0:
        raise ValueError("[FAIL-FAST] ข้อมูลราคาปิด (close) ในแท่งเทียนไม่ถูกต้องหรือ <= 0")

    atr = sum(trs) / len(trs) if trs else 0.0
    atr_pct = (atr / last_close) * 100.0

    # Volatility Classification for Binary Options (1m - 5m)
    # Healthy range: 0.0002 <= gk_vol <= 0.0035
    if 0.0002 <= gk_vol <= 0.0035:
        score = 25.0
        regime = "HEALTHY"
        tag = "🟢 ผันผวนสุขภาพดี (Healthy)"
    elif gk_vol > 0.0035:
        score = 8.0
        regime = "SPIKY"
        tag = "🔴 ผันผวนกระชาก (Spiky Risk)"
    else:
        score = 0.0
        regime = "DEAD"
        tag = "⚪ กราฟนิ่งสนิท (Flatline)"

    return {
        "score": score,
        "regime": regime,
        "gk_vol": round(gk_vol * 10000.0, 2),
        "parkinson_vol": round(parkinson_vol * 10000.0, 2),
        "atr_pct": round(atr_pct, 4),
        "status_tag": tag
    }


# ==============================================================================
# SECTION 3: คุณภาพแท่งเทียน & กรอง Noise (feature-engineering, ta-lib - 30 คะแนน)
# ==============================================================================
def analyze_candlestick_quality(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    คำนวณ Body %, Close Position, กรอง Doji, Wick Noise และ Frozen Bars
    (Skills: feature-engineering, ta-lib, ohlcv-processing)
    """
    if not candles or len(candles) < 5:
        return {
            "score": 0.0,
            "body_ratio": 0.0,
            "doji_rate": 100.0,
            "wick_ratio": 100.0,
            "close_pos": 0.5,
            "frozen_count": 0,
            "verdict": "ข้อมูลไม่เพียงพอ"
        }

    total = len(candles)
    body_ratios = []
    wick_ratios = []
    close_positions = []
    doji_count = 0
    frozen_count = 0
    bullish_count = 0
    bearish_count = 0

    for c in candles:
        o = float(c.get("open", 0))
        h = float(c.get("max", c.get("high", 0)))
        l = float(c.get("min", c.get("low", 0)))
        cl = float(c.get("close", 0))

        c_range = max(h - l, 1e-6)
        body = abs(cl - o)
        b_ratio = (body / c_range) * 100.0
        body_ratios.append(b_ratio)

        # Frozen bar detection (Skill: ohlcv-processing)
        if h == l == o == cl:
            frozen_count += 1

        # Close position in range (Skill: feature-engineering)
        cp = (cl - l) / c_range
        close_positions.append(cp)

        # Wick noise ratio
        upper_w = h - max(o, cl)
        lower_w = min(o, cl) - l
        w_ratio = ((upper_w + lower_w) / c_range) * 100.0
        wick_ratios.append(w_ratio)

        # Doji definition: Body <= 15% (Skill: ta-lib)
        if b_ratio <= 15.0:
            doji_count += 1

        if cl > o:
            bullish_count += 1
        elif cl < o:
            bearish_count += 1

    avg_body = sum(body_ratios) / total
    avg_wick = sum(wick_ratios) / total
    avg_cp = sum(close_positions) / total
    doji_rate = (doji_count / total) * 100.0

    # 1. Base Body Score (0 - 25 pts)
    body_score = min(25.0, (avg_body / 60.0) * 25.0)

    # 2. Doji Penalty (Skill: ta-lib)
    doji_penalty = (doji_rate / 100.0) * 20.0

    # 3. Extreme Close Position Bonus (Skill: feature-engineering)
    cp_bonus = 5.0 if (avg_cp >= 0.70 or avg_cp <= 0.30) else 2.0

    # 4. Frozen Bar Penalty (Skill: ohlcv-processing)
    frozen_penalty = frozen_count * 10.0

    candle_score = max(0.0, min(30.0, body_score + cp_bonus - doji_penalty - frozen_penalty))

    return {
        "score": round(candle_score, 1),
        "body_ratio": round(avg_body, 1),
        "doji_rate": round(doji_rate, 1),
        "wick_ratio": round(avg_wick, 1),
        "close_pos": round(avg_cp, 2),
        "frozen_count": frozen_count,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count
    }


# ==============================================================================
# SECTION 4: สภาวะตลาด & โมเมนตัม (Skill: regime-detection - 15 คะแนน)
# ==============================================================================
def compute_hurst_exponent(prices: List[float]) -> float:
    """คำนวณ Hurst Exponent แบบย่อ (Rescaled Range) เพื่อวัด Trend Persistence vs Mean Reversion"""
    if not prices or len(prices) < 8:
        return 0.50
    try:
        returns = [math.log(prices[i] / max(prices[i - 1], 1e-6)) for i in range(1, len(prices))]
        if not returns or len(returns) < 4:
            return 0.50
        mean_r = sum(returns) / len(returns)
        deviations = [r - mean_r for r in returns]
        cum_dev = []
        c = 0.0
        for d in deviations:
            c += d
            cum_dev.append(c)
        r_range = max(cum_dev) - min(cum_dev)
        variance = sum(d ** 2 for d in deviations) / len(deviations)
        std_dev = math.sqrt(max(variance, 1e-12))
        if std_dev <= 0 or r_range <= 0:
            return 0.50
        rs = r_range / std_dev
        n = len(returns)
        h = math.log(max(rs, 1.0001)) / math.log(n)
        return max(0.0, min(1.0, float(h)))
    except Exception:
        return 0.50


def analyze_market_regime(
    candles_dict: Dict[str, List[Dict[str, Any]]],
    primary_candles: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    ตรวจจับสภาวะตลาด (Trend vs Chop) และความสอดคล้อง Multi-TF (M1 vs M5 vs M15)
    (Skill: regime-detection)
    """
    candles_m1 = candles_dict.get("m1", [])
    candles_m5 = candles_dict.get("m5", [])
    candles_m15 = candles_dict.get("m15", [])
    
    target_candles = primary_candles or candles_m5 or candles_m1
    if not target_candles or len(target_candles) < 5:
        return {
            "score": 0.0,
            "regime": "UNKNOWN",
            "tag": "⚪ ไม่มีข้อมูล",
            "bias_pct": 0.0,
            "hurst": 0.50,
            "mtf_aligned": False
        }

    bullish = sum(1 for c in target_candles if float(c.get("close", 0)) > float(c.get("open", 0)))
    bearish = sum(1 for c in target_candles if float(c.get("close", 0)) < float(c.get("open", 0)))
    total = len(target_candles)
    bias = max(bullish, bearish) / total * 100.0

    # Multi-TF Trend Alignment Check
    def get_tf_bias(c_list: List[Dict[str, Any]]) -> int:
        if not c_list or len(c_list) < 3:
            return 0
        cl_first = float(c_list[0].get("open", 0))
        cl_last = float(c_list[-1].get("close", 0))
        if cl_last > cl_first:
            return 1
        elif cl_last < cl_first:
            return -1
        return 0

    b_m1 = get_tf_bias(candles_m1)
    b_m5 = get_tf_bias(candles_m5)
    b_m15 = get_tf_bias(candles_m15)
    mtf_aligned = (b_m1 == b_m5 == b_m15 and b_m5 != 0)

    # Hurst Exponent on target candle closes
    closes = [float(c.get("close", 0)) for c in target_candles if float(c.get("close", 0)) > 0]
    hurst = compute_hurst_exponent(closes)

    if (bias >= 70.0 or (bias >= 65.0 and mtf_aligned)) and hurst >= 0.50:
        score = 15.0
        regime = "STRONG_TREND"
        tag = "🟢 เทรนด์ชัดเจน (Strong Trend)"
        if mtf_aligned:
            tag += " [M1-M5-M15 สอดคล้อง]"
    elif bias >= 55.0 or hurst >= 0.52:
        score = 10.0
        regime = "CLEAN_SWING"
        tag = "🟡 สวิงมีทิศทาง (Clean Swing)"
    else:
        score = 3.0
        regime = "CHOP_NOISE"
        tag = "⚪ ไซด์เวย์ไร้ทิศทาง (Chop Noise)"

    return {
        "score": score,
        "regime": regime,
        "tag": tag,
        "bias_pct": round(bias, 1),
        "hurst": round(hurst, 2),
        "mtf_aligned": mtf_aligned
    }


# ==============================================================================
# SECTION 5: ระบบแนวรับ-แนวต้าน & พื้นที่วิ่ง (Room-to-Run Index - 10 คะแนน)
# ==============================================================================
def analyze_support_resistance(candles_m5: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
    """
    คำนวณแนวรับ-แนวต้าน Pivot Points, Dynamic Levels (Swing H/L) และ Room-to-Run (พื้นที่วิ่ง)
    """
    if not candles_m5 or len(candles_m5) < 5 or current_price <= 0:
        return {
            "score": 5.0,
            "status": "NORMAL",
            "tag": "⚪ S/R ปกติ",
            "room_to_run": "มีพื้นที่ปานกลาง",
            "dist_resistance": 999.0,
            "dist_support": 999.0,
            "pivot": 0.0,
            "r1": 0.0,
            "s1": 0.0
        }

    highs = [float(c.get("max", c.get("high", 0))) for c in candles_m5]
    lows = [float(c.get("min", c.get("low", 0))) for c in candles_m5]
    closes = [float(c.get("close", 0)) for c in candles_m5]

    swing_high = max(highs)
    swing_low = min(lows)
    last_h = highs[-1]
    last_l = lows[-1]
    last_c = closes[-1]

    # Standard Pivot Point calculation
    pivot = (last_h + last_l + last_c) / 3.0
    r1 = (2.0 * pivot) - last_l
    s1 = (2.0 * pivot) - last_h

    # Resistance candidates above price
    res_candidates = [v for v in [swing_high, r1] if v > current_price]
    nearest_res = min(res_candidates) if res_candidates else swing_high

    # Support candidates below price
    sup_candidates = [v for v in [swing_low, s1] if v < current_price]
    nearest_sup = max(sup_candidates) if sup_candidates else swing_low

    dist_res = max(0.0, nearest_res - current_price)
    dist_sup = max(0.0, current_price - nearest_sup)
    min_dist = min(dist_res, dist_sup)
    dist_pct = (min_dist / current_price) * 100.0

    if dist_pct >= 0.03:
        score = 10.0
        status = "CLEAR"
        tag = "🟢 มีพื้นที่วิ่งโล่ง (Room to Run)"
        desc = f"ห่างแนวต้าน {dist_res:.5f} / แนวรับ {dist_sup:.5f}"
    elif dist_pct <= 0.008:
        score = 2.0
        status = "BARRIER"
        tag = "🔴 ชิดแนวกำแพง S/R (เสี่ยงเด้งกลับ)"
        desc = f"ราคาชิดแนวรับ/ต้านมากเกินไป ({min_dist:.5f})"
    else:
        score = 6.0
        status = "NORMAL"
        tag = "🟡 ระยะ S/R ปานกลาง"
        desc = f"ระยะห่าง {min_dist:.5f}"

    return {
        "score": score,
        "status": status,
        "tag": tag,
        "room_to_run": desc,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "pivot": round(pivot, 5),
        "r1": round(r1, 5),
        "s1": round(s1, 5),
        "dist_resistance": dist_res,
        "dist_support": dist_sup
    }


# ==============================================================================
# SECTION 6: 4 ท่าไม้ตายเฉพาะทาง Binary Options (10 คะแนน)
# ==============================================================================
def analyze_exclusive_binary_edges(
    symbol: str,
    candles_tick: List[Dict[str, Any]],
    current_price: float,
    payout: float = 84.0
) -> Dict[str, Any]:
    """
    4 ท่าไม้ตายเฉพาะทาง Binary Options:
    1. Round Number Warning (.00 / .50 / .80)
    2. Tick Velocity & Micro-Momentum (30s)
    3. OTC Step-Ladder Pattern
    4. P(Win) Breakeven Math & Payout Stability
    """
    score = 10.0
    tags = []
    is_otc = symbol.upper().endswith("-OTC")

    # 1. Round Number Magnet (.00 / .50 / .80)
    is_jpy = "JPY" in symbol.upper()
    if is_jpy:
        mod_1 = current_price % 1.0
        if abs(mod_1 - 0.0) < 0.03 or abs(mod_1 - 0.50) < 0.03 or abs(mod_1 - 0.80) < 0.03 or abs(mod_1 - 1.0) < 0.03:
            score -= 4.0
            tags.append("⚠️ ชิดตัวเลขกลม JPY (.00/.50)")
    else:
        price_str = f"{current_price:.5f}"
        last_3 = price_str[-3:] if len(price_str) >= 3 else "000"
        if last_3 in ("000", "500", "800", "00", "50"):
            score -= 4.0
            tags.append("⚠️ ชิดตัวเลขกลม (.00/.50)")

    # 2. Tick Velocity & Micro-Movement (30s)
    if candles_tick and len(candles_tick) >= 10:
        tick_count = len(candles_tick)
        if tick_count >= 15:
            score += 2.0
            tags.append("⚡ Tick ไหลต่อเนื่อง")
        elif tick_count < 5:
            score -= 5.0
            tags.append("⚠️ Tick ชะลอตัว")

    # 3. OTC Step-Ladder Pattern
    if is_otc:
        score += 2.0
        tags.append("🧬 OTC 24/7 Engine")

    # 4. P(Win) Breakeven Math & Payout Stability
    payout_val = float(payout) if payout else 84.0
    be_win_rate = (1.0 / (1.0 + (payout_val / 100.0))) * 100.0
    if payout_val >= 88.0:
        score += 1.0
        tags.append(f"💎 Payout สูง ({int(round(payout_val))}% | BE: {be_win_rate:.1f}%)")

    score = max(0.0, min(10.0, score))
    return {
        "score": score,
        "edge_tags": tags,
        "tag": " | ".join(tags) if tags else "ปกติ",
        "be_win_rate": round(be_win_rate, 1)
    }


# ==============================================================================
# SECTION 7: ฟังก์ชันรวมประเมินคะแนนเชิงปริมาณ 100 คะแนนเต็ม & จัดอันดับ
# ==============================================================================
def evaluate_symbol_comprehensive(
    symbol: str,
    candles_dict: Dict[str, List[Dict[str, Any]]],
    payout: float,
    route: str = "TURBO",
    dt_utc: Optional[datetime] = None
) -> Dict[str, Any]:
    """ประเมินคู่เงิน 1 คู่เงินแบบครบ 3 มิติ (7 Skills + 4 Edges + S/R Room to Run) รวม 100 คะแนนเต็ม"""
    if not symbol:
        raise ValueError("[FAIL-FAST] ไม่ระบุชื่อคู่เงิน (symbol ว่างเปล่า)")
    if payout is None or float(payout) <= 0.0:
        raise ValueError(f"[FAIL-FAST] ค่า Payout ของ {symbol} ไม่ถูกต้องหรือไม่พบ ({payout})")
    payout = float(payout)

    if not isinstance(candles_dict, dict) or not candles_dict:
        raise ValueError(f"[FAIL-FAST] ไม่พบโครงสร้างข้อมูลแท่งเทียน (candles_dict) สำหรับ {symbol}")

    candles_tick = candles_dict.get("tick", [])
    candles_m1 = candles_dict.get("m1", candles_dict.get("candles", []))
    candles_m5 = candles_dict.get("m5", [])
    candles_m15 = candles_dict.get("m15", [])

    current_price = 0.0
    for src in [candles_m1, candles_tick, candles_m5, candles_m15]:
        if src and len(src) > 0:
            current_price = float(src[-1].get("close", 0.0))
            if current_price > 0.0:
                break

    if current_price <= 0.0:
        raise ValueError(f"[FAIL-FAST] ราคาปัจจุบัน (Current Price) ของ {symbol} ไม่ถูกต้อง ({current_price})")

    # 1. Liquidity & Session (10 pts)
    session_res = analyze_session_liquidity(symbol, dt_utc=dt_utc)

    # 2. Volatility Metrics (25 pts)
    vol_res = analyze_volatility_metrics(candles_m1 or candles_m5)

    # 3. Candlestick Quality & Doji Ban (30 pts)
    candle_res = analyze_candlestick_quality(candles_m1 or candles_m5)

    # 4. Market Regime & MTF Momentum (15 pts)
    regime_res = analyze_market_regime(candles_dict, primary_candles=candles_m5 or candles_m1)

    # 5. Support & Resistance & Room to Run (10 pts)
    sr_res = analyze_support_resistance(candles_m5 or candles_m15 or candles_m1, current_price)

    # 6. Exclusive Binary Edges (10 pts)
    edge_res = analyze_exclusive_binary_edges(symbol, candles_tick, current_price, payout=payout)

    # Total Composite Score (0 - 100 pts)
    total_score = (
        session_res["score"] +
        vol_res["score"] +
        candle_res["score"] +
        regime_res["score"] +
        sr_res["score"] +
        edge_res["score"]
    )
    total_score = max(0.0, min(100.0, total_score))

    if total_score >= 78.0:
        stars, grade, verdict = "⭐⭐⭐⭐⭐", "EXCELLENT", "🟢 สัญญาณสวยมาก กราฟวิ่งคม เนื้อแน่น พื้นที่โล่ง"
    elif total_score >= 65.0:
        stars, grade, verdict = "⭐⭐⭐⭐", "GOOD", "🟢 สัญญาณดี กราฟมีทิศทาง ความผันผวนปกติ"
    elif total_score >= 50.0:
        stars, grade, verdict = "⭐⭐⭐", "FAIR", "🟡 สัญญาณปานกลาง มี Doji หรือไส้กวนบ้าง"
    else:
        stars, grade, verdict = "⚠️", "POOR", "🔴 สัญญาณไม่ดี กราฟนิ่ง/กระชาก หรือติดกำแพง S/R"

    return {
        "symbol": symbol,
        "score": round(total_score, 1),
        "stars": stars,
        "grade": grade,
        "payout": payout,
        "route": route,
        "current_price": current_price,
        "session_tag": session_res["liquidity_tag"],
        "volatility_regime": vol_res["status_tag"],
        "body_ratio": candle_res["body_ratio"],
        "doji_rate": candle_res["doji_rate"],
        "regime_tag": regime_res["tag"],
        "room_to_run": sr_res["tag"],
        "edge_tag": edge_res["tag"],
        "verdict": verdict,
        "details": {
            "session": session_res,
            "volatility": vol_res,
            "candle": candle_res,
            "regime": regime_res,
            "support_resistance": sr_res,
            "binary_edges": edge_res
        }
    }


def rank_tradable_symbols(candidates: List[Dict[str, Any]], dt_utc: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    วิเคราะห์และจัดอันดับคู่เงินน่าเทรด (Rank 1 ถึง Rank N)
    เกณฑ์ Tie-Breaker: Score สูงสุด -> Payout สูงสุด -> Body Ratio สูงสุด
    """
    if not candidates:
        return []

    evaluated_list: List[Dict[str, Any]] = []
    for item in candidates:
        sym = item.get("symbol", "")
        if not sym:
            raise ValueError("[FAIL-FAST] พบ candidate ที่ไม่มีชื่อสัญลักษณ์ (symbol ว่างเปล่า)")

        candles_dict = item.get("candles")
        if not candles_dict:
            raise ValueError(f"[FAIL-FAST] ไม่พบข้อมูลแท่งเทียน (candles) สำหรับ {sym}")
        if isinstance(candles_dict, list):
            candles_dict = {"m1": candles_dict}

        raw_payout = item.get("binary_max_payout") if item.get("binary_max_payout") is not None else item.get("payout", item.get("max_payout"))
        if raw_payout is None:
            raise ValueError(f"[FAIL-FAST] ไม่พบข้อมูล Payout สำหรับ {sym}")
        payout = float(raw_payout)
        if payout <= 0.0:
            raise ValueError(f"[FAIL-FAST] Payout ของ {sym} ต้องมากกว่า 0 (ได้รับ {payout})")

        route = item.get("best_route") or item.get("route")
        if not route:
            raise ValueError(f"[FAIL-FAST] ไม่พบช่องทางเทรด (route) สำหรับ {sym}")

        eval_res = evaluate_symbol_comprehensive(
            symbol=sym,
            candles_dict=candles_dict,
            payout=payout,
            route=route,
            dt_utc=dt_utc
        )
        evaluated_list.append(eval_res)

    # จัดอันดับ 3 ชั้น: Score ➡️ Payout ➡️ Body Ratio
    evaluated_list.sort(key=lambda x: (x["score"], x["payout"], x["body_ratio"]), reverse=True)

    for idx, item in enumerate(evaluated_list, start=1):
        item["rank"] = idx

    return evaluated_list


# ==============================================================================
# SECTION 8: Scan Helper & Multi-TF Fetching (Pure In-Memory / Zero SSD)
# ==============================================================================
def scan_single_symbol(
    sym: str,
    all_profits: Dict[str, Any],
    turbo_actives: Dict[str, Any],
    binary_actives: Dict[str, Any],
    min_payout: float = 84.0,
    api: Any = None
) -> Dict[str, Any]:
    """ตรวจสอบสถานะตลาดและ Payout 3 สัญญา (Turbo, Binary, Digital) ของคู่เงินเดียว"""
    candidates = [sym, f"{sym}-op", f"{sym}-OP"]
    best_entry = {
        "symbol": sym,
        "matched_sym": sym,
        "turbo_pct": 0.0,
        "turbo_open": False,
        "binary_pct": 0.0,
        "binary_open": False,
        "digital_pct": 0.0,
        "digital_open": False,
        "max_payout": 0.0,
        "binary_max_payout": 0.0,
        "is_tradable": False,
        "binary_tradable": False,
        "meets_payout": False,
        "best_route": "ปิดรับคำสั่ง"
    }

    for c in candidates:
        p_info = all_profits.get(c, {})
        turbo_p = p_info.get("turbo") or 0.0
        binary_p = p_info.get("binary") or 0.0
        turbo_open = binary_open = digital_open = False
        digital_pct = 0.0

        for aid, ainfo in turbo_actives.items():
            name = ainfo.get('name', '').replace('front.', '')
            if name.upper() == c.upper():
                if ainfo.get('enabled') is True and ainfo.get('is_suspended') is False:
                    turbo_open = True
                break

        for aid, ainfo in binary_actives.items():
            name = ainfo.get('name', '').replace('front.', '')
            if name.upper() == c.upper():
                if ainfo.get('enabled') is True and ainfo.get('is_suspended') is False:
                    binary_open = True
                break

        if (turbo_open or binary_open or "-OTC" in c) and api is not None and hasattr(api, "get_digital_payout"):
            try:
                import iqoptionapi.constants as OP_code
                if c in OP_code.ACTIVES:
                    dp = api.get_digital_payout(c, seconds=0.3)
                    if isinstance(dp, (int, float)) and dp > 0:
                        digital_pct = float(dp)
                        digital_open = True
            except Exception:
                pass

        turbo_pct = round(turbo_p * 100.0, 1) if turbo_p > 0 else 0.0
        binary_pct = round(binary_p * 100.0, 1) if binary_p > 0 else 0.0
        max_p = max(turbo_pct, binary_pct, digital_pct)
        binary_max_p = max(turbo_pct, binary_pct)
        is_open = (turbo_open and turbo_pct > 0) or (binary_open and binary_pct > 0) or (digital_open and digital_pct > 0)
        binary_tradable = (turbo_open and turbo_pct >= min_payout) or (binary_open and binary_pct >= min_payout)

        if is_open and max_p >= best_entry["max_payout"]:
            if turbo_open and turbo_pct >= binary_pct and turbo_pct > 0:
                best_route = f"TURBO ({turbo_pct:.1f}%)"
            elif binary_open and binary_pct > 0:
                best_route = f"BINARY ({binary_pct:.1f}%)"
            elif digital_open and digital_pct > 0:
                best_route = f"DIGITAL ({digital_pct:.1f}%)"
            else:
                best_route = "ปิดรับคำสั่ง"

            best_entry = {
                "symbol": sym,
                "matched_sym": c,
                "turbo_pct": turbo_pct,
                "turbo_open": turbo_open,
                "binary_pct": binary_pct,
                "binary_open": binary_open,
                "digital_pct": digital_pct,
                "digital_open": digital_open,
                "max_payout": max_p,
                "binary_max_payout": binary_max_p,
                "is_tradable": is_open,
                "binary_tradable": binary_tradable,
                "meets_payout": binary_tradable,
                "best_route": best_route
            }

    return best_entry


def fetch_multi_tf_candles(api: Any, symbol: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    ดึงข้อมูลราคา Multi-TF (Tick, M1, M5, M15) จาก IQ Option API ตรงเข้า RAM
    (PURE IN-MEMORY: ไม่บันทึกไฟล์ CSV หรือดิสก์ใดๆ ทั้งสิ้น)
    """
    now_ts = time.time()
    candles_dict: Dict[str, List[Dict[str, Any]]] = {"tick": [], "m1": [], "m5": [], "m15": []}
    if api is None:
        return candles_dict

    # Configuration: Tick (1s x 30), M1 (60s x 20), M5 (300s x 20), M15 (900s x 20)
    tf_specs = [
        ("m1", 60, 20),
        ("m5", 300, 20),
        ("m15", 900, 20),
        ("tick", 1, 30)
    ]

    for tf, sec, count in tf_specs:
        try:
            c_data = api.get_candles(symbol, sec, count, now_ts)
            if isinstance(c_data, list):
                candles_dict[tf] = c_data
        except Exception as e:
            logger.debug(f"[symbols_selection] Exception fetching {tf} for {symbol}: {e}")

    return candles_dict


# ==============================================================================
# SECTION 9: Visual Table Formatter
# ==============================================================================
def get_visual_width(text: str) -> int:
    """คำนวณความกว้างข้อความ โดยจัดการสระภาษาไทยและอีโมจิให้ตรงช่อง 100%"""
    THAI_ZERO_WIDTH = {
        0x0E31, 0x0E34, 0x0E35, 0x0E36, 0x0E37, 0x0E38, 0x0E39, 0x0E3A,
        0x0E47, 0x0E48, 0x0E49, 0x0E4A, 0x0E4B, 0x0E4C, 0x0E4D, 0x0E4E
    }
    EMOJIS_WIDTH_2 = {"🔴", "🟢", "🟡", "⚪", "⭐", "🏆", "📌", "🎯", "⚡", "🧬", "⚠️"}
    w = 0
    for ch in text:
        cp = ord(ch)
        if cp in THAI_ZERO_WIDTH:
            continue
        if ch in EMOJIS_WIDTH_2:
            w += 2
        else:
            w += 1
    return w


def pad_visual(text: str, target_width: int) -> str:
    """เติมช่องว่างให้ความกว้างในการแสดงผลตรงกับ target_width พอดี"""
    current_w = get_visual_width(text)
    return text + (" " * max(0, target_width - current_w))


def build_summary_table(
    results_set_a: List[Dict[str, Any]],
    results_set_b: List[Dict[str, Any]],
    ranked_results: List[Dict[str, Any]],
    top_picks: List[str],
    min_payout: float,
    max_symbols: int
) -> str:
    """สร้างตารางรายงานสรุปสถานะตลาดและการจัดอันดับคู่เงิน"""
    tz_thailand = timezone(timedelta(hours=7))
    now_dt = datetime.now(tz_thailand)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append("=" * 115)
    lines.append(f"  IQ OPTION 3D ASSET & PAYOUT SCANNER (ประมวลผลเมื่อ: {now_str})")
    lines.append(f"  ตรวจสอบคู่เงิน Focus ครบ 3 มิติ (Payout >= {int(min_payout)}% + 7 Skills + 4 Edges + S/R)")
    lines.append("=" * 115)

    def format_pair_line(r: Dict[str, Any]) -> str:
        sym = r["symbol"]
        if not r["binary_open"]:
            b_str = "🔴 Binary: ปิด"
        elif r["binary_pct"] >= min_payout:
            b_str = f"🟢 Binary: {int(round(r['binary_pct']))}%"
        else:
            b_str = f"🟡 Binary: {int(round(r['binary_pct']))}%"
        t_str = f"⚪ Turbo: {int(round(r['turbo_pct']))}%" if r["turbo_open"] else "⚪ Turbo: ปิด"
        d_str = f"⚪ Digital: {int(round(r['digital_pct']))}%" if r["digital_open"] else "⚪ Digital: ปิด"
        col_sym = pad_visual(f"  • {sym}", 18)
        col_bin = pad_visual(b_str, 20)
        col_tur = pad_visual(t_str, 20)
        col_dig = pad_visual(d_str, 20)
        return f"{col_sym}| {col_bin}| {col_tur}| {col_dig}"

    lines.append(f"\n--- SET A: คู่เงินหลัก [{len(results_set_a)} คู่] ---")
    for r in results_set_a:
        lines.append(format_pair_line(r))
    lines.append(f"\n--- SET B: คู่เงินสำรอง [{len(results_set_b)} คู่] ---")
    for r in results_set_b:
        lines.append(format_pair_line(r))

    if ranked_results:
        lines.append("\n" + "=" * 115)
        lines.append(f"--- ตารางจัดอันดับคู่เงินน่าเทรด (Rank 1 - {len(ranked_results)}) ---")
        for r in ranked_results:
            verdict_text = r.get("verdict", "").replace("🟢 ", "").replace("🟡 ", "").replace("🔴 ", "")
            vol_text = r.get("volatility_regime", "").replace("🟢 ", "").replace("🟡 ", "").replace("⚪ ", "").replace("🔴 ", "")
            regime_text = r.get("regime_tag", "").replace("🟢 ", "").replace("🟡 ", "").replace("⚪ ", "").replace("🔴 ", "")
            room_text = r.get("room_to_run", "").replace("🟢 ", "").replace("🟡 ", "").replace("🔴 ", "")
            col_rank = pad_visual(f"  อันดับ {r['rank']}: {r['symbol']}", 26)
            col_score = pad_visual(f"คะแนน: {r['score']}/100", 18)
            col_payout = pad_visual(f"Payout: {int(round(r['payout']))}%", 16)
            col_room = pad_visual(room_text, 32)
            lines.append(f"{col_rank}| {col_score}| {col_payout}| {col_room}")
            lines.append(f"          └── วิเคราะห์: {verdict_text}, {vol_text}, {regime_text}")

    lines.append("\n" + "=" * 115)
    lines.append(f"🏆 สรุปผลคัดเลือก Top {max_symbols} คู่เงิน: {', '.join(top_picks) if top_picks else 'ไม่พบคู่ที่ผ่านเกณฑ์'}")
    lines.append("=" * 115)
    return "\n".join(lines)


# ==============================================================================
# SECTION 10: Single Source of Truth Atomic Persistence
# ==============================================================================
def save_symbols_ssot(symbols: List[str], target_path: Path, payouts: Optional[Dict[str, float]] = None) -> None:
    """
    บันทึก Top picks ลง config_setting/symbols.json แบบ Atomic Write ปลอดภัย 100%
    ตามสเปก Single Source of Truth: {"symbols": ["EURUSD", ...], "payouts": {"EURUSD": 87, ...}}
    """
    if not symbols:
        raise ValueError("[FAIL-FAST] ไม่พบคู่เงินสำหรับบันทึก (symbols ว่างเปล่า)")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.parent / f"{target_path.name}.tmp"
    data: Dict[str, Any] = {"symbols": symbols}
    if payouts is not None:
        data["payouts"] = payouts

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, target_path)


# ==============================================================================
# SECTION 11: Main Selector Entrypoint (run_selector)
# ==============================================================================
def run_selector(data_adapter: Optional[Any] = None, silent: bool = True) -> List[str]:
    """
    ฟังก์ชันหลักในการคัดเลือกและจัดอันดับคู่เงินสำหรับบอท (runner.py) และ Standalone
    
    Args:
        data_adapter: Broker data adapter instance (หากระบุ จะดึง api จาก instance นี้ ไม่สร้าง connection ใหม่)
        silent: True หากไม่ต้องการพิมพ์ตารางสรุป และไม่บันทึกไฟล์รายงาน txt ลงดิสก์ (เขียนเฉพาะ symbols.json)
        
    Returns:
        List[str]: รายชื่อ Top picks คู่เงิน (เช่น ["EURUSD", "GBPUSD", ...])
    """
    try:
        current_dir = Path(__file__).resolve().parent
        symbols_user_path = current_dir / "symbols_user.json"
        settings_path = current_dir / "settings.json"

        # 1. Load candidate pairs from symbols_user.json
        if not symbols_user_path.is_file():
            raise FileNotFoundError(f"[FAIL-FAST] ไม่พบไฟล์คู่เงิน: {symbols_user_path}")
        with open(symbols_user_path, "r", encoding="utf-8") as f:
            user_symbols_data = json.load(f)

        set_a = [str(s).strip().upper() for s in user_symbols_data.get("SET_A", []) if str(s).strip()]
        set_b = [str(s).strip().upper() for s in user_symbols_data.get("SET_B", []) if str(s).strip()]
        if not set_a and not set_b:
            raise ValueError(f"[FAIL-FAST] ไม่พบรายชื่อคู่เงินใน SET_A หรือ SET_B ของ {symbols_user_path.name}")

        # 2. Load settings (min_payout & max_symbols) from settings.json
        if not settings_path.is_file():
            raise FileNotFoundError(f"[FAIL-FAST] ไม่พบไฟล์คอนฟิกหลัก: {settings_path}")
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)

        min_payout = float(settings.get("min_payout", 84.0))
        max_symbols = int(settings.get("max_symbols", 4))
        if min_payout <= 0:
            raise ValueError(f"[FAIL-FAST] min_payout ใน {settings_path.name} ไม่ถูกต้อง ({min_payout})")
        if max_symbols <= 0:
            raise ValueError(f"[FAIL-FAST] max_symbols ใน {settings_path.name} ไม่ถูกต้อง ({max_symbols})")

        # 3. Handle Broker API instance
        api = None
        if data_adapter is not None:
            api = getattr(data_adapter, "api", None) or getattr(getattr(data_adapter, "_broker", None), "api", None)
            if api is None:
                raise ValueError("[FAIL-FAST] data_adapter ถูกส่งเข้ามาแต่ไม่พบ IQ Option API instance")
        else:
            # Standalone mode: load credentials and connect safely
            account = settings.get("account", {})
            email = account.get("iq_email", "").strip()
            password = account.get("iq_password", "").strip()
            if not email or not password or email.startswith("ใส่") or password.startswith("ใส่"):
                raise ValueError(f"[FAIL-FAST] ข้อมูลบัญชี (iq_email, iq_password) ใน {settings_path.name} ไม่ถูกต้องหรือสูญหาย")

            try:
                from iqoptionapi.stable_api import IQ_Option
            except ImportError:
                raise ImportError("[FAIL-FAST] ไม่พบไลบรารี iqoptionapi กรุณาติดตั้งก่อนใช้งาน")

            api = IQ_Option(email, password)
            ok, reason = api.connect()
            if not ok:
                raise ConnectionError(f"[FAIL-FAST] เชื่อมต่อ IQ Option ล้มเหลว: {reason}")
            time.sleep(1)

        # 4. Populate OP_code.ACTIVES dynamically
        init_data = api.get_all_init() or {}
        turbo_actives = init_data.get('result', {}).get('turbo', {}).get('actives', {})
        binary_actives = init_data.get('result', {}).get('binary', {}).get('actives', {})
        try:
            import iqoptionapi.constants as OP_code
            for cat in ["turbo", "binary"]:
                for aid, ainfo in init_data.get("result", {}).get(cat, {}).get("actives", {}).items():
                    name = ainfo.get("name", "").replace("front.", "")
                    if name:
                        OP_code.ACTIVES[name] = int(aid)
        except Exception as e:
            logger.debug(f"[symbols_selection] Active registration note: {e}")

        # 5. Fetch Payouts (get_all_profit) with retries
        all_profits = {}
        for _ in range(3):
            try:
                all_profits = api.get_all_profit()
                if all_profits and len(all_profits) > 0:
                    break
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

        if not all_profits:
            raise RuntimeError("[FAIL-FAST] ไม่สามารถดึงอัตราผลตอบแทน (get_all_profit) จากโบรกเกอร์ได้")

        # 6. Scan Focus Symbols
        results_set_a = [scan_single_symbol(s, all_profits, turbo_actives, binary_actives, min_payout=min_payout, api=api) for s in set_a]
        results_set_b = [scan_single_symbol(s, all_profits, turbo_actives, binary_actives, min_payout=min_payout, api=api) for s in set_b]

        # Prioritize SET_A first, then SET_B (up to 12 candidates)
        candidates_to_eval: List[Dict[str, Any]] = []
        for r in results_set_a:
            if r["binary_tradable"] and len(candidates_to_eval) < 12:
                candidates_to_eval.append(r)
        for r in results_set_b:
            if r["binary_tradable"] and len(candidates_to_eval) < 12:
                candidates_to_eval.append(r)

        if not candidates_to_eval:
            raise RuntimeError(f"[FAIL-FAST] ไม่พบคู่เงินใดที่ผ่านเกณฑ์ Payout >= {int(min_payout)}% ใน SET_A และ SET_B")

        # 7. Candlestick Fetching (PURE IN-MEMORY: ZERO SSD WRITE)
        for item in candidates_to_eval:
            sym_to_fetch = item["matched_sym"]
            candles_dict = fetch_multi_tf_candles(api, sym_to_fetch)
            item["candles"] = candles_dict

        # 8. Full 100-Point Quantitative Evaluation & Ranking
        ranked_results = rank_tradable_symbols(candidates_to_eval)

        # 9. Extract Top Picks
        top_picks: List[str] = []
        payout_map: Dict[str, int] = {}
        for r in ranked_results:
            sym_clean = r["symbol"].replace("-op", "").replace("-OP", "")
            if sym_clean not in top_picks:
                top_picks.append(sym_clean)
                payout_map[sym_clean] = int(round(r.get("payout", 0)))
            if len(top_picks) >= max_symbols:
                break

        if not top_picks:
            raise RuntimeError("[FAIL-FAST] ไม่พบคู่เงินที่ผ่านการคัดเลือกหลังการจัดอันดับ")

        # 10. Atomic Save to config_setting/symbols.json (Single Source of Truth)
        symbols_ssot_path = current_dir / "symbols.json"
        save_symbols_ssot(top_picks, symbols_ssot_path, payouts=payout_map)

        # 11. Reporting & Summary Display
        if not silent:
            summary_table = build_summary_table(
                results_set_a=results_set_a,
                results_set_b=results_set_b,
                ranked_results=ranked_results,
                top_picks=top_picks,
                min_payout=min_payout,
                max_symbols=max_symbols
            )
            print("\n" + summary_table)
            print(f"\n[OK] คัดกรองและจัดอันดับ Top {max_symbols} คู่เงินเสร็จสมบูรณ์เรียบร้อยค่ะ!")

        return top_picks

    except Exception as e:
        logger.exception(f"[FAIL-FAST] เกิดข้อผิดพลาดร้ายแรงใน run_selector: {e}")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    try:
        picks = run_selector(data_adapter=None, silent=False)
        print(f"\n[OUTPUT] Final Selected Symbols: {picks}")
    except Exception as ex:
        sys.exit(1)
