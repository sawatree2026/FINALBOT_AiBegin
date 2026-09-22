"""
IQ Option Ultimate All-in-One Asset & Market Scanner (บอทเช็ครายการเปิดเทรดสมบูรณ์แบบ)
รวมระบบตรวจสอบสถานะตลาด 5 มิติ และอัตราผลตอบแทน Payout (%) จากโบรกเกอร์ IQ Option
+ Secondary Filter (7 Skills + 4 Edges + S/R) สำหรับวิเคราะห์และจัดอันดับคู่เงินน่าเทรด
"""
import os
import sys
import json
import time
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union

# Ensure UTF-8 output safely for Windows CMD / PowerShell
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
            "is_otc": True, "score": 10.0, "liquidity_level": "HIGH",
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
        score, level = 10.0, "HIGH"
        tag = "🟢 สภาพคล่องสูง (Peak Session)"
        desc = f"ตลาดเปิดพร้อมกัน ({', '.join(open_currs)}) ใน {', '.join(active_sessions)}"
    elif len(open_currs) == 1:
        score, level = 7.0, "MEDIUM"
        tag = "🟡 สภาพคล่องปานกลาง (Single Open)"
        desc = f"ตลาดเปิด 1 สกุล ({', '.join(open_currs)}) ใน {', '.join(active_sessions)}"
    else:
        score, level = 3.0, "LOW"
        tag = "⚪ สภาพคล่องต่ำ (Off-Hours)"
        desc = f"อยู่นอกเวลาทำการหลัก ({curr_a}/{curr_b})"
        
    return {
        "is_otc": False, "score": score, "liquidity_level": level,
        "liquidity_tag": tag, "description": desc
    }

# ==============================================================================
# SECTION 2: วิเคราะห์ความผันผวน & แท่งเทียน
# ==============================================================================
def analyze_volatility_metrics(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """คำนวณ Garman-Klass Volatility, Parkinson Range, และ Normalized ATR%"""
    if not candles or len(candles) < 5:
        return {"score": 0.0, "regime": "NO_DATA", "gk_vol": 0.0, "atr_pct": 0.0, "status_tag": "⚪ ไม่มีข้อมูล"}
        
    gk_terms, ranges, trs = [], [], []
    prev_close = None
    for c in candles:
        o = float(c.get("open", 0))
        h = float(c.get("max", c.get("high", 0)))
        l = float(c.get("min", c.get("low", 0)))
        cl = float(c.get("close", 0))
        if h <= 0 or l <= 0 or o <= 0 or cl <= 0:
            continue
        u = math.log(max(h / max(l, 1e-6), 1.000001))
        v = math.log(max(cl / max(o, 1e-6), 1e-6))
        gk_term = 0.5 * (u ** 2) - (2.0 * math.log(2.0) - 1.0) * (v ** 2)
        gk_terms.append(gk_term)
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
    
    if 0.0002 <= gk_vol <= 0.0035:
        score, regime, tag = 25.0, "HEALTHY", "🟢 ผันผวนสุขภาพดี (Healthy)"
    elif gk_vol > 0.0035:
        score, regime, tag = 8.0, "SPIKY", "🔴 ผันผวนกระชาก (Spiky Risk)"
    else:
        score, regime, tag = 0.0, "DEAD", "⚪ กราฟนิ่งสนิท (Flatline)"
        
    return {
        "score": score, "regime": regime,
        "gk_vol": round(gk_vol * 10000.0, 2), "atr_pct": round(atr_pct, 4), "status_tag": tag
    }

def analyze_candlestick_quality(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """คำนวณ Body %, Close Position, กรอง Doji, Wick Noise และ Frozen Bars"""
    if not candles or len(candles) < 5:
        return {"score": 0.0, "body_ratio": 0.0, "doji_rate": 100.0, "wick_ratio": 100.0, 
                "close_pos": 0.5, "frozen_count": 0, "verdict": "ข้อมูลไม่เพียงพอ"}
                
    total = len(candles)
    body_ratios, wick_ratios, close_positions = [], [], []
    doji_count = frozen_count = bullish_count = bearish_count = 0
    
    for c in candles:
        o = float(c.get("open", 0))
        h = float(c.get("max", c.get("high", 0)))
        l = float(c.get("min", c.get("low", 0)))
        cl = float(c.get("close", 0))
        c_range = max(h - l, 1e-6)
        body = abs(cl - o)
        b_ratio = (body / c_range) * 100.0
        body_ratios.append(b_ratio)
        if h == l == o == cl: frozen_count += 1
        cp = (cl - l) / c_range
        close_positions.append(cp)
        upper_w = h - max(o, cl)
        lower_w = min(o, cl) - l
        w_ratio = ((upper_w + lower_w) / c_range) * 100.0
        wick_ratios.append(w_ratio)
        if b_ratio <= 15.0: doji_count += 1
        if cl > o: bullish_count += 1
        elif cl < o: bearish_count += 1
        
    avg_body = sum(body_ratios) / total
    avg_wick = sum(wick_ratios) / total
    avg_cp = sum(close_positions) / total
    doji_rate = (doji_count / total) * 100.0
    
    body_score = min(25.0, (avg_body / 60.0) * 25.0)
    doji_penalty = (doji_rate / 100.0) * 20.0
    cp_bonus = 5.0 if (avg_cp >= 0.70 or avg_cp <= 0.30) else 2.0
    frozen_penalty = frozen_count * 10.0
    candle_score = max(0.0, min(30.0, body_score + cp_bonus - doji_penalty - frozen_penalty))
    
    return {
        "score": round(candle_score, 1), "body_ratio": round(avg_body, 1), "doji_rate": round(doji_rate, 1),
        "wick_ratio": round(avg_wick, 1), "close_pos": round(avg_cp, 2), "frozen_count": frozen_count,
        "bullish_count": bullish_count, "bearish_count": bearish_count
    }

def analyze_market_regime(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """ตรวจจับสภาวะตลาด (Trend vs Chop)"""
    if not candles or len(candles) < 5:
        return {"score": 0.0, "regime": "UNKNOWN", "tag": "⚪ ไม่มีข้อมูล"}
    bullish = sum(1 for c in candles if float(c.get("close", 0)) > float(c.get("open", 0)))
    bearish = sum(1 for c in candles if float(c.get("close", 0)) < float(c.get("open", 0)))
    total = len(candles)
    bias = max(bullish, bearish) / total * 100.0
    if bias >= 70.0:
        score, regime, tag = 15.0, "STRONG_TREND", "🟢 เทรนด์ชัดเจน (Strong Trend)"
    elif bias >= 55.0:
        score, regime, tag = 10.0, "CLEAN_SWING", "🟡 สวิงมีทิศทาง (Clean Swing)"
    else:
        score, regime, tag = 3.0, "CHOP_NOISE", "⚪ ไซด์เวย์ไร้ทิศทาง (Chop Noise)"
    return {"score": score, "regime": regime, "tag": tag, "bias_pct": round(bias, 1)}

# ==============================================================================
# SECTION 3: ระบบแนวรับ-แนวต้าน และ 4 ท่าไม้ตายเฉพาะทาง Binary Options
# ==============================================================================
def analyze_support_resistance(candles_m5: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
    """คำนวณแนวรับ-แนวต้าน Swing High / Low และ Room-to-Run"""
    if not candles_m5 or len(candles_m5) < 5 or current_price <= 0:
        return {"score": 5.0, "status": "NORMAL", "tag": "⚪ S/R ปกติ", "room_to_run": "มีพื้นที่ปานกลาง", 
                "dist_resistance": 999.0, "dist_support": 999.0}
    highs = [float(c.get("max", c.get("high", 0))) for c in candles_m5]
    lows = [float(c.get("min", c.get("low", 0))) for c in candles_m5]
    swing_high, swing_low = max(highs), min(lows)
    dist_res = max(0.0, swing_high - current_price)
    dist_sup = max(0.0, current_price - swing_low)
    min_dist = min(dist_res, dist_sup)
    dist_pct = (min_dist / current_price) * 100.0
    
    if dist_pct >= 0.03:
        score, status, tag = 10.0, "CLEAR", "🟢 มีพื้นที่วิ่งโล่ง (Room to Run)"
        desc = f"ห่างแนวต้าน {dist_res:.5f} / แนวรับ {dist_sup:.5f}"
    elif dist_pct <= 0.008:
        score, status, tag = 2.0, "BARRIER", "🔴 ชิดแนวกำแพง S/R (เสี่ยงเด้งกลับ)"
        desc = f"ราคาชิดแนวรับ/ต้านมากเกินไป ({min_dist:.5f})"
    else:
        score, status, tag = 6.0, "NORMAL", "🟡 ระยะ S/R ปานกลาง"
        desc = f"ระยะห่าง {min_dist:.5f}"
        
    return {"score": score, "status": status, "tag": tag, "room_to_run": desc, 
            "swing_high": swing_high, "swing_low": swing_low, 
            "dist_resistance": dist_res, "dist_support": dist_sup}

def analyze_exclusive_binary_edges(symbol: str, candles_tick: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
    """4 ท่าไม้ตายเฉพาะทาง: Tick Momentum, Round Number, OTC Step-Ladder"""
    score = 10.0
    tags = []
    is_otc = symbol.upper().endswith("-OTC")
    
    # 1. Round Number Magnet
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
            
    # 2. Tick Velocity
    if candles_tick and len(candles_tick) >= 10:
        tick_count = len(candles_tick)
        if tick_count >= 15:
            score += 2.0
            tags.append("⚡ Tick ไหลต่อเนื่อง")
        elif tick_count < 5:
            score -= 5.0
            tags.append("⚠️ Tick ชะลอตัว")
            
    # 3. OTC Step-Ladder
    if is_otc:
        score += 2.0
        tags.append("🧬 OTC 24/7 Engine")
        
    score = max(0.0, min(10.0, score))
    return {"score": score, "edge_tags": tags, "tag": " | ".join(tags) if tags else "ปกติ"}

# ==============================================================================
# SECTION 4: ฟังก์ชันหลักประเมินคู่เงินเดี่ยว & จัดอันดับความน่าเทรด
# ==============================================================================
def evaluate_symbol_comprehensive(symbol: str, candles_dict: Dict[str, List[Dict[str, Any]]], 
                                  payout: float, route: str = "TURBO", dt_utc: Optional[datetime] = None) -> Dict[str, Any]:
    """ประเมินคู่เงิน 1 คู่เงินแบบครบ 3 มิติ (7 Skills + 4 Edges + S/R)"""
    if not symbol: raise ValueError("[FAIL-FAST] ไม่ระบุชื่อคู่เงิน")
    if payout is None or float(payout) <= 0.0: raise ValueError(f"[FAIL-FAST] ค่า Payout ของ {symbol} ไม่ถูกต้อง")
    payout = float(payout)
    if not isinstance(candles_dict, dict) or not candles_dict: raise ValueError(f"[FAIL-FAST] ไม่พบข้อมูลแท่งเทียนสำหรับ {symbol}")
    
    candles_tick = candles_dict.get("tick", [])
    candles_m1 = candles_dict.get("m1", candles_dict.get("candles", []))
    candles_m5 = candles_dict.get("m5", [])
    candles_m15 = candles_dict.get("m15", [])
    
    current_price = 0.0
    for src in [candles_m1, candles_tick, candles_m5, candles_m15]:
        if src and len(src) > 0:
            current_price = float(src[-1].get("close", 0.0))
            if current_price > 0.0: break
            
    if current_price <= 0.0: raise ValueError(f"[FAIL-FAST] ราคาปัจจุบันของ {symbol} ไม่ถูกต้อง")
    
    session_res = analyze_session_liquidity(symbol, dt_utc=dt_utc)
    vol_res = analyze_volatility_metrics(candles_m1 or candles_m5)
    candle_res = analyze_candlestick_quality(candles_m1 or candles_m5)
    regime_res = analyze_market_regime(candles_m5 or candles_m1)
    sr_res = analyze_support_resistance(candles_m5 or candles_m15 or candles_m1, current_price)
    edge_res = analyze_exclusive_binary_edges(symbol, candles_tick, current_price)
    
    total_score = sum([session_res["score"], vol_res["score"], candle_res["score"], 
                       regime_res["score"], sr_res["score"], edge_res["score"]])
    total_score = max(0.0, min(100.0, total_score))
    
    if total_score >= 78.0: stars, grade, verdict = "⭐⭐⭐⭐⭐", "EXCELLENT", "🟢 สัญญาณสวยมาก กราฟวิ่งคม เนื้อแน่น พื้นที่โล่ง"
    elif total_score >= 65.0: stars, grade, verdict = "⭐⭐⭐⭐", "GOOD", "🟢 สัญญาณดี กราฟมีทิศทาง ความผันผวนปกติ"
    elif total_score >= 50.0: stars, grade, verdict = "⭐⭐⭐", "FAIR", "🟡 สัญญาณปานกลาง มี Doji หรือไส้กวนบ้าง"
    else: stars, grade, verdict = "⚠️", "POOR", "🔴 สัญญาณไม่ดี กราฟนิ่ง/กระชาก หรือติดกำแพง S/R"
    
    return {
        "symbol": symbol, "score": round(total_score, 1), "stars": stars, "grade": grade,
        "payout": payout, "route": route, "current_price": current_price,
        "session_tag": session_res["liquidity_tag"], "volatility_regime": vol_res["status_tag"],
        "body_ratio": candle_res["body_ratio"], "doji_rate": candle_res["doji_rate"],
        "regime_tag": regime_res["tag"], "room_to_run": sr_res["tag"], "edge_tag": edge_res["tag"],
        "verdict": verdict,
        "details": {"session": session_res, "volatility": vol_res, "candle": candle_res, 
                    "regime": regime_res, "support_resistance": sr_res, "binary_edges": edge_res}
    }

def rank_tradable_symbols(candidates: List[Dict[str, Any]], dt_utc: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """วิเคราะห์และจัดอันดับคู่เงินน่าเทรด (Rank 1 ถึง Rank N)"""
    if not candidates: return []
    evaluated_list: List[Dict[str, Any]] = []
    for item in candidates:
        sym = item.get("symbol", "")
        if not sym: raise ValueError("[FAIL-FAST] พบ candidate ที่ไม่มีชื่อสัญลักษณ์")
        candles_dict = item.get("candles")
        if not candles_dict: raise ValueError(f"[FAIL-FAST] ไม่พบข้อมูลแท่งเทียนสำหรับ {sym}")
        if isinstance(candles_dict, list): candles_dict = {"m1": candles_dict}
        
        raw_payout = item.get("binary_max_payout") if item.get("binary_max_payout") is not None else item.get("payout", item.get("max_payout"))
        if raw_payout is None: raise ValueError(f"[FAIL-FAST] ไม่พบข้อมูล Payout สำหรับ {sym}")
        payout = float(raw_payout)
        if payout <= 0.0: raise ValueError(f"[FAIL-FAST] Payout ของ {sym} ต้องมากกว่า 0")
        
        route = item.get("best_route") or item.get("route")
        if not route: raise ValueError(f"[FAIL-FAST] ไม่พบช่องทางเทรดสำหรับ {sym}")
        
        eval_res = evaluate_symbol_comprehensive(symbol=sym, candles_dict=candles_dict, payout=payout, route=route, dt_utc=dt_utc)
        evaluated_list.append(eval_res)
        
    evaluated_list.sort(key=lambda x: (x["score"], x["payout"], x["body_ratio"]), reverse=True)
    for idx, item in enumerate(evaluated_list, start=1):
        item["rank"] = idx
    return evaluated_list

# ==============================================================================
# SECTION 5: Main Scanner Logic (IQ Option API Integration)
# ==============================================================================
MIN_PAYOUT: float = 84.0

def load_focus_symbols(file_path: Path) -> Dict[str, List[str]]:
    """Loads SET A and SET B focus symbols from symbols_user_config.txt."""
    if not file_path.is_file():
        raise FileNotFoundError(f"[ERR] ไม่พบไฟล์คอนฟิกคู่เงิน: {file_path}")
    focus: Dict[str, List[str]] = {"SET_A": [], "SET_B": []}
    current_set = "SET_A"
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip()
            if not clean or clean.startswith("-") or "รายชื่อคู่เงิน" in clean or "หลักการ" in clean:
                continue
            if "SET A" in clean.upper():
                current_set = "SET_A"
                continue
            if "SET B" in clean.upper():
                current_set = "SET_B"
                continue
            if len(clean) >= 6 and " " not in clean:
                sym = clean.upper()
                if sym not in focus[current_set]:
                    focus[current_set].append(sym)
    return focus

def scan_single_symbol(sym: str, all_profits: Dict[str, Any], turbo_actives: Dict[str, Any], binary_actives: Dict[str, Any], api: Any = None) -> Dict[str, Any]:
    """Inspects a single symbol across standard and -op contract variants."""
    candidates = [sym, f"{sym}-op", f"{sym}-OP"]
    best_entry = {
        "symbol": sym, "matched_sym": sym, "turbo_pct": 0.0, "turbo_open": False,
        "binary_pct": 0.0, "binary_open": False, "digital_pct": 0.0, "digital_open": False,
        "max_payout": 0.0, "binary_max_payout": 0.0, "is_tradable": False, "binary_tradable": False,
        "meets_payout": False, "best_route": "ปิดรับคำสั่ง"
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
                if ainfo.get('enabled') is True and ainfo.get('is_suspended') is False: turbo_open = True
                break
        for aid, ainfo in binary_actives.items():
            name = ainfo.get('name', '').replace('front.', '')
            if name.upper() == c.upper():
                if ainfo.get('enabled') is True and ainfo.get('is_suspended') is False: binary_open = True
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
        binary_tradable = (turbo_open and turbo_pct >= MIN_PAYOUT) or (binary_open and binary_pct >= MIN_PAYOUT)
        
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
                "symbol": sym, "matched_sym": c, "turbo_pct": turbo_pct, "turbo_open": turbo_open,
                "binary_pct": binary_pct, "binary_open": binary_open, "digital_pct": digital_pct,
                "digital_open": digital_open, "max_payout": max_p, "binary_max_payout": binary_max_p,
                "is_tradable": is_open, "binary_tradable": binary_tradable, "meets_payout": binary_tradable,
                "best_route": best_route
            }
    return best_entry

def fetch_multi_tf_candles(api: Any, symbol: str) -> Dict[str, List[Dict[str, Any]]]:
    """ดึงข้อมูลราคา Multi-TF (Tick, M1, M5, M15) จาก IQ Option API"""
    now_ts = time.time()
    candles_dict = {"tick": [], "m1": [], "m5": [], "m15": []}
    if api is None: return candles_dict
    
    for tf, sec, count in [("m1", 60, 20), ("m5", 300, 20), ("m15", 900, 20), ("tick", 1, 30)]:
        try:
            c_data = api.get_candles(symbol, sec, count, now_ts)
            if isinstance(c_data, list):
                candles_dict[tf] = c_data
        except Exception:
            pass
    return candles_dict

def main(silent: bool = False):
    if not silent:
        print("=" * 80)
        print("    IQ OPTION ULTIMATE ALL-IN-ONE ASSET & PAYOUT SCANNER (บอทเช็คตลาด)    ")
        print("=" * 80)
        
    current_dir = Path(__file__).resolve().parent
    focus_file_path = current_dir / "symbols_user_config.txt"
    if not focus_file_path.is_file():
        raise FileNotFoundError(f"[ERR] ไม่พบไฟล์คอนฟิกคู่เงิน: {focus_file_path}")
    settings_path = current_dir / "settings_filter.json"
    if not settings_path.is_file():
        raise FileNotFoundError(f"[ERR] ไม่พบไฟล์คอนฟิกหลัก: {settings_path}")
        
    for old_pattern in ["symbols_onoff_*.txt", "symbols_active_*.txt", "active_symbols*.txt"]:
        for old_file in current_dir.glob(old_pattern):
            try: old_file.unlink()
            except Exception: pass
            
    focus_dict = load_focus_symbols(focus_file_path)
    set_a = focus_dict.get("SET_A", [])
    set_b = focus_dict.get("SET_B", [])
    if not set_a and not set_b:
        if not silent: print(f"[ERR] ไม่พบรายชื่อคู่เงินใน {focus_file_path.name}")
        return []
        
    try:
        from iqoptionapi.stable_api import IQ_Option
    except ImportError:
        if not silent: print("[ERR] iqoptionapi library is not installed.")
        return []
        
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
    account = settings.get("account", {})
    email = account.get("iq_email", "").strip()
    password = account.get("iq_password", "").strip()
    if not email or not password:
        raise ValueError(f"iq_email หรือ iq_password ใน {settings_path.name} ไม่ถูกต้องหรือสูญหาย")
        
    max_symbols = int(settings.get("max_symbols", 4))
    if not silent:
        print(f"[CONFIG] โหลดคอนฟิกจาก {settings_path.name} สำเร็จ (max_symbols: {max_symbols})")
        print(f"[CONN] Connecting to IQ Option as {email}...")
        
    api = IQ_Option(email, password)
    ok, reason = api.connect()
    if not ok:
        if not silent: print(f"[ERR] Login failed: {reason}")
        return []
    if not silent:
        print(f"[CONN] Connected successfully! (Balance Mode: {api.get_balance_mode()})")
    time.sleep(1)
    
    if not silent: print("[DATA] Scanning market status strictly for Focus Symbols...")
    init_data = api.get_all_init() or {}
    turbo_actives = init_data.get('result', {}).get('turbo', {}).get('actives', {})
    binary_actives = init_data.get('result', {}).get('binary', {}).get('actives', {})
    try:
        import iqoptionapi.constants as OP_code
        for cat in ["turbo", "binary"]:
            for aid, ainfo in init_data.get("result", {}).get(cat, {}).get("actives", {}).items():
                name = ainfo.get("name", "").replace("front.", "")
                if name: OP_code.ACTIVES[name] = int(aid)
    except Exception: pass
    
    all_profits = {}
    for _ in range(3):
        try:
            all_profits = api.get_all_profit()
            if all_profits and len(all_profits) > 0: break
            time.sleep(1)
        except Exception: time.sleep(1)
        
    results_set_a = [scan_single_symbol(s, all_profits, turbo_actives, binary_actives, api=api) for s in set_a]
    results_set_b = [scan_single_symbol(s, all_profits, turbo_actives, binary_actives, api=api) for s in set_b]
    
    candidates_to_eval = []
    for r in results_set_a:
        if r["binary_tradable"] and len(candidates_to_eval) < 12: candidates_to_eval.append(r)
    for r in results_set_b:
        if r["binary_tradable"] and len(candidates_to_eval) < 12: candidates_to_eval.append(r)
        
    if not silent:
        print(f"[DATA] พบ {len(candidates_to_eval)} คู่เงินที่ผ่านเกณฑ์ Payout >= {int(MIN_PAYOUT)}% -> ดึงแท่งเทียน 4 TF...")
        
    for item in candidates_to_eval:
        sym_to_fetch = item["matched_sym"]
        candles_dict = fetch_multi_tf_candles(api, sym_to_fetch)
        item["candles"] = candles_dict
        
    ranked_results = rank_tradable_symbols(candidates_to_eval)
    
    top_picks: List[str] = []
    for r in ranked_results:
        sym_clean = r["symbol"].replace("-op", "").replace("-OP", "")
        if sym_clean not in top_picks: top_picks.append(sym_clean)
        if len(top_picks) >= max_symbols: break
        
    tz_thailand = timezone(timedelta(hours=7))
    now_dt = datetime.now(tz_thailand)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    timestamp_file_str = now_dt.strftime("%Y%m%d_%H%M")
    
    lines = []
    lines.append("=" * 115)
    lines.append(f"  IQ OPTION 3D FOCUS ASSET SCANNER REPORT (บันทึกเมื่อ: {now_str})")
    lines.append(f"  ตรวจสอบคู่เงินจาก {focus_file_path.name} ครบ 3 มิติ (Payout >= {int(MIN_PAYOUT)}% + 7 Skills + 4 Edges + S/R)")
    lines.append("=" * 115)
    
    def get_visual_width(text: str) -> int:
        THAI_ZERO_WIDTH = {0x0E31, 0x0E34, 0x0E35, 0x0E36, 0x0E37, 0x0E38, 0x0E39, 0x0E3A, 0x0E47, 0x0E48, 0x0E49, 0x0E4A, 0x0E4B, 0x0E4C, 0x0E4D, 0x0E4E}
        EMOJIS_WIDTH_2 = {"🔴", "🟢", "🟡", "⚪", "⭐", "🏆", "📌", "🎯", "⚡", "🧬", "⚠️"}
        w = 0
        for ch in text:
            cp = ord(ch)
            if cp in THAI_ZERO_WIDTH: continue
            if ch in EMOJIS_WIDTH_2: w += 2
            else: w += 1
        return w

    def pad_visual(text: str, target_width: int) -> str:
        current_w = get_visual_width(text)
        return text + (" " * max(0, target_width - current_w))

    def format_pair_line(r: Dict[str, Any]) -> str:
        sym = r["symbol"]
        if not r["binary_open"]: b_str = "🔴 Binary: ปิด"
        elif r["binary_pct"] >= MIN_PAYOUT: b_str = f"🟢 Binary: {int(round(r['binary_pct']))}%"
        else: b_str = f"🟡 Binary: {int(round(r['binary_pct']))}%"
        t_str = f"⚪ Turbo: {int(round(r['turbo_pct']))}%" if r["turbo_open"] else "⚪ Turbo: ปิด"
        d_str = f"⚪ Digital: {int(round(r['digital_pct']))}%" if r["digital_open"] else "⚪ Digital: ปิด"
        col_sym = pad_visual(f"  • {sym}", 18)
        col_bin = pad_visual(b_str, 20)
        col_tur = pad_visual(t_str, 20)
        col_dig = pad_visual(d_str, 20)
        return f"{col_sym}| {col_bin}| {col_tur}| {col_dig}"

    lines.append(f"\n--- SET A: คู่เงินหลัก [{len(set_a)} คู่] ---")
    for r in results_set_a: lines.append(format_pair_line(r))
    lines.append(f"\n--- SET B: คู่เงินสำรอง [{len(set_b)} คู่] ---")
    for r in results_set_b: lines.append(format_pair_line(r))
    
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
    output_text = "\n".join(lines)
    
    try:
        for old_pattern in ["symbols_onoff_*.txt", "symbols_active_*.txt", "active_symbols*.txt"]:
            for old_f in current_dir.glob(old_pattern):
                try: old_f.unlink()
                except Exception: pass
        report_file = current_dir / f"symbols_onoff_{timestamp_file_str}.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(output_text)
            
        local_trade_symbols_path = current_dir / "symbols_trade.json"
        with open(local_trade_symbols_path, "w", encoding="utf-8") as f:
            json.dump(top_picks, f, indent=2, ensure_ascii=False)
            
        local_symbols_legacy_path = current_dir / "symbols.json"
        if local_symbols_legacy_path.is_file():
            try: local_symbols_legacy_path.unlink()
            except Exception: pass
            
        if not silent:
            print(f"[SAVE] บันทึกรายงานสถานะตลาด -> {report_file.name}")
            print(f"[SAVE] บันทึก Top {max_symbols} คู่เงินลง symbols_trade.json: {top_picks}")
    except Exception as e:
        if not silent: print(f"[ERR] Failed to write report/symbols file: {e}")
        
    if not silent:
        print("\n" + output_text)
        print(f"\n[OK] คัดกรองและจัดอันดับ Top {max_symbols} คู่เงินเสร็จสมบูรณ์เรียบร้อยค่ะ!")
    return top_picks

if __name__ == "__main__":
    main()
