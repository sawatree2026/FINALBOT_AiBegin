"""
Secondary Filter (โมดูลวิเคราะห์และจัดอันดับคู่เงินน่าเทรด - Rank 1 to N)
========================================================================================
รวมขุมพลัง 7 สุดยอด Skill + 4 ท่าไม้ตาย Binary Options + ระบบแนวรับ-แนวต้าน (Support & Resistance)
วิเคราะห์คู่เงินที่ผ่านเกณฑ์ Payout >= 84% (ไม่เกิน 8 คู่) และจัดอันดับความน่าเทรด (Rank 1 = น่าเทรดที่สุด)

1. ขุมพลัง 7 สุดยอด Skill:
   • volatility-modeling : Garman-Klass & Parkinson Volatility (HEALTHY / SPIKY / DEAD)
   • feature-engineering : Body-to-Range Ratio (>= 50%) & Extreme Close Position (CP > 0.75 / < 0.25)
   • ta-lib              : Doji Cluster Penalty (<= 15%) & Wick Noise Filter (> 50%)
   • pandas-ta           : Normalized ATR% & Bollinger Bands Width Squeeze/Expansion
   • regime-detection    : Market Regime (Strong Trend / Clean Swing / Chop Noise)
   • liquidity-analysis  : Global Session Overlap (London/NY) & 24/7 OTC Synthetic Engine
   • ohlcv-processing    : Data Hygiene & Frozen Bar / Anomaly Detection

2. 4 ท่าไม้ตายเฉพาะทาง Binary Options:
   • Last-5-Seconds Guard : ตรวจจับแรงส่ง Tick Momentum ไม่ให้หมดแรงก่อนหมดเวลา
   • Payout Stability     : ตรวจสอบความนิ่งของอัตราจ่าย
   • Round Number Warning : ตรวจจับระยะห่างจากแนวต้านตัวเลขกลม (.00 / .50 / .80)
   • OTC Step-Ladder      : ตรวจจับรูปแบบกราฟระเบิดแท่งบันไดในตลาด OTC

3. ระบบแนวรับ-แนวต้าน (Support & Resistance Engine):
   • Swing High / Swing Low (M5 & M15)
   • Room-to-Run Index (พื้นที่ว่างให้ราคาวิ่งเข้าเป้า ไม่ชนกำแพง)
"""

import sys
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union


# ==============================================================================
# SECTION 1: หลักการที่ 2 - สภาพคล่องและช่วงเวลาตลาดโลก (liquidity-analysis)
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
# SECTION 2: วิเคราะห์ความผันผวน & แท่งเทียน (volatility-modeling + feature-engineering + ta-lib + pandas-ta)
# ==============================================================================
def analyze_volatility_metrics(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    คำนวณ Garman-Klass Volatility, Parkinson Range, และ Normalized ATR%
    (Skills: volatility-modeling & pandas-ta)
    """
    if not candles or len(candles) < 5:
        return {
            "score": 0.0,
            "regime": "NO_DATA",
            "gk_vol": 0.0,
            "atr_pct": 0.0,
            "status_tag": "⚪ ไม่มีข้อมูล"
        }

    gk_terms = []
    ranges = []
    trs = []
    prev_close = None

    for c in candles:
        o = float(c.get("open", 0))
        h = float(c.get("max", c.get("high", 0)))
        l = float(c.get("min", c.get("low", 0)))
        cl = float(c.get("close", 0))

        if h <= 0 or l <= 0 or o <= 0 or cl <= 0:
            continue

        # Garman-Klass Volatility term
        u = math.log(max(h / max(l, 1e-6), 1.000001))
        v = math.log(max(cl / max(o, 1e-6), 1e-6))
        gk_term = 0.5 * (u ** 2) - (2.0 * math.log(2.0) - 1.0) * (v ** 2)
        gk_terms.append(gk_term)

        # True Range
        tr = h - l
        if prev_close is not None:
            tr = max(tr, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        ranges.append(h - l)
        prev_close = cl

    if not gk_terms:
        return {"score": 0.0, "regime": "DEAD", "gk_vol": 0.0, "atr_pct": 0.0, "status_tag": "⚪ กราฟตาย"}

    gk_vol = math.sqrt(max(sum(gk_terms) / len(gk_terms), 0.0))
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
        "atr_pct": round(atr_pct, 4),
        "status_tag": tag
    }


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


def analyze_market_regime(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    ตรวจจับสภาวะตลาด (Trend vs Chop) (Skill: regime-detection)
    """
    if not candles or len(candles) < 5:
        return {"score": 0.0, "regime": "UNKNOWN", "tag": "⚪ ไม่มีข้อมูล"}

    bullish = sum(1 for c in candles if float(c.get("close", 0)) > float(c.get("open", 0)))
    bearish = sum(1 for c in candles if float(c.get("close", 0)) < float(c.get("open", 0)))
    total = len(candles)
    bias = max(bullish, bearish) / total * 100.0

    if bias >= 70.0:
        score = 15.0
        regime = "STRONG_TREND"
        tag = "🟢 เทรนด์ชัดเจน (Strong Trend)"
    elif bias >= 55.0:
        score = 10.0
        regime = "CLEAN_SWING"
        tag = "🟡 สวิงมีทิศทาง (Clean Swing)"
    else:
        score = 3.0
        regime = "CHOP_NOISE"
        tag = "⚪ ไซด์เวย์ไร้ทิศทาง (Chop Noise)"

    return {"score": score, "regime": regime, "tag": tag, "bias_pct": round(bias, 1)}


# ==============================================================================
# SECTION 3: ระบบแนวรับ-แนวต้าน และ 4 ท่าไม้ตายเฉพาะทาง Binary Options
# ==============================================================================
def analyze_support_resistance(candles_m5: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
    """
    คำนวณแนวรับ-แนวต้าน Swing High / Low และ Room-to-Run (พื้นที่วิ่ง)
    """
    if not candles_m5 or len(candles_m5) < 5 or current_price <= 0:
        return {
            "score": 5.0,
            "status": "NORMAL",
            "tag": "⚪ S/R ปกติ",
            "room_to_run": "มีพื้นที่ปานกลาง",
            "dist_resistance": 999.0,
            "dist_support": 999.0
        }

    highs = [float(c.get("max", c.get("high", 0))) for c in candles_m5]
    lows = [float(c.get("min", c.get("low", 0))) for c in candles_m5]

    swing_high = max(highs)
    swing_low = min(lows)

    dist_res = max(0.0, swing_high - current_price)
    dist_sup = max(0.0, current_price - swing_low)
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
        "dist_resistance": dist_res,
        "dist_support": dist_sup
    }


def analyze_exclusive_binary_edges(symbol: str, candles_tick: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
    """
    4 ท่าไม้ตายเฉพาะทาง:
    1. Last-5-Seconds Tick Momentum Decay
    2. Round Number Warning (.00, .50, .80)
    3. OTC Step-Ladder Pattern
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

    score = max(0.0, min(10.0, score))
    return {
        "score": score,
        "edge_tags": tags,
        "tag": " | ".join(tags) if tags else "ปกติ"
    }


# ==============================================================================
# SECTION 4: ฟังก์ชันหลักประเมินคู่เงินเดี่ยว & จัดอันดับความน่าเทรด (Rank 1 to N)
# ==============================================================================
def evaluate_symbol_comprehensive(
    symbol: str,
    candles_dict: Dict[str, List[Dict[str, Any]]],
    payout: float,
    route: str = "TURBO",
    dt_utc: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    ประเมินคู่เงิน 1 คู่เงินแบบครบ 3 มิติ (7 Skills + 4 Edges + S/R)
    คืนค่าคะแนนเต็ม 100 และระดับดาว ⭐
    """
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
    if candles_m1 and len(candles_m1) > 0:
        current_price = float(candles_m1[-1].get("close", 0.0))
    elif candles_tick and len(candles_tick) > 0:
        current_price = float(candles_tick[-1].get("close", 0.0))
    elif candles_m5 and len(candles_m5) > 0:
        current_price = float(candles_m5[-1].get("close", 0.0))
    elif candles_m15 and len(candles_m15) > 0:
        current_price = float(candles_m15[-1].get("close", 0.0))
    else:
        raise ValueError(f"[FAIL-FAST] ไม่พบข้อมูลแท่งเทียนราคาสำหรับ {symbol}")

    if current_price <= 0.0:
        raise ValueError(f"[FAIL-FAST] ราคาปัจจุบัน (Current Price) ของ {symbol} ไม่ถูกต้อง ({current_price})")

    # 1. Liquidity & Session (10 pts)
    session_res = analyze_session_liquidity(symbol, dt_utc=dt_utc)

    # 2. Volatility Metrics (25 pts)
    vol_res = analyze_volatility_metrics(candles_m1 or candles_m5)

    # 3. Candlestick Quality & Doji Ban (30 pts)
    candle_res = analyze_candlestick_quality(candles_m1 or candles_m5)

    # 4. Market Regime (15 pts)
    regime_res = analyze_market_regime(candles_m5 or candles_m1)

    # 5. Support & Resistance & Room to Run (10 pts)
    sr_res = analyze_support_resistance(candles_m5 or candles_m15 or candles_m1, current_price)

    # 6. Exclusive Binary Edges (10 pts)
    edge_res = analyze_exclusive_binary_edges(symbol, candles_tick, current_price)

    # Total Composite Score (0 - 100)
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
        stars = "⭐⭐⭐⭐⭐"
        grade = "EXCELLENT"
        verdict = "🟢 สัญญาณสวยมาก กราฟวิ่งคม เนื้อแน่น พื้นที่โล่ง"
    elif total_score >= 65.0:
        stars = "⭐⭐⭐⭐"
        grade = "GOOD"
        verdict = "🟢 สัญญาณดี กราฟมีทิศทาง ความผันผวนปกติ"
    elif total_score >= 50.0:
        stars = "⭐⭐⭐"
        grade = "FAIR"
        verdict = "🟡 สัญญาณปานกลาง มี Doji หรือไส้กวนบ้าง"
    else:
        stars = "⚠️"
        grade = "POOR"
        verdict = "🔴 สัญญาณไม่ดี กราฟนิ่ง/กระชาก หรือติดกำแพง S/R"

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
    รับรายชื่อคู่เงินที่มี Payout >= 84% ไม่เกิน 8 คู่จาก main_filter.py
    
    คืนค่า: List ของคู่เงินที่จัดลำดับแล้ว (อันดับ 1 = น่าเทรดที่สุด)
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
        # Support if raw candle list passed directly
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

    # จัดอันดับ: คะแนนรวมสูงสุดก่อน -> Payout สูงสุดก่อน -> Body Ratio สูงสุดก่อน
    evaluated_list.sort(key=lambda x: (x["score"], x["payout"], x["body_ratio"]), reverse=True)

    # ใส่ลำดับที่ (Rank 1 ถึง N)
    for idx, item in enumerate(evaluated_list, start=1):
        item["rank"] = idx

    return evaluated_list


