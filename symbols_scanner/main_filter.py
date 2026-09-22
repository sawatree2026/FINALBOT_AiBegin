"""
IQ Option Ultimate All-in-One Asset & Market Scanner (บอทเช็ครายการเปิดเทรดสมบูรณ์แบบ)
========================================================================================
รวมระบบตรวจสอบสถานะตลาด 5 มิติ และอัตราผลตอบแทน Payout (%) จากโบรกเกอร์ IQ Option
100% ตรงจาก Server โดยไม่มีการตัดทิ้ง พร้อมระบุช่องทางเทรดที่เปิดรับคำสั่งจริง

- อ่านรายชื่อคู่เงินจาก: symbols_scanner/symbols_user_config.txt เท่านั้น
- อ่านข้อมูลบัญชีจาก: symbols_scanner/settings_filter.json เท่านั้น
- บันทึกรายงานฉบับสมบูรณ์ไปที่: symbols_scanner/symbols_onoff_YYYYMMDD_HHMM.txt (1 ไฟล์ล่าสุดเสมอ)
- บันทึกผลลัพธ์คู่เงินเทรด: symbols_scanner/symbols_trade.json (Standalone - ไม่ส่งออกไปบอท)
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

# Ensure UTF-8 output safely for Windows CMD / PowerShell
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# เชื่อมต่อโมดูลวิเคราะห์และจัดอันดับตลาดรวม (Secondary Filter: 7 Skills + 4 Edges + S/R)
try:
    from symbols_scanner.secondary_filter import rank_tradable_symbols, evaluate_symbol_comprehensive
except ImportError:
    from secondary_filter import rank_tradable_symbols, evaluate_symbol_comprehensive

# ข้อบังคับเกณฑ์อัตราจ่ายขั้นต่ำ (Minimum Payout Threshold)
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
    """Inspects a single symbol across standard and -op contract variants across Turbo, Binary, Digital."""
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

        turbo_open = False
        binary_open = False
        digital_open = False
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
    """ดึงข้อมูลราคา Multi-TF (Tick, M1, M5, M15) จาก IQ Option API ให้ไฟล์รองวิเคราะห์"""
    now_ts = time.time()
    candles_dict = {"tick": [], "m1": [], "m5": [], "m15": []}
    if api is None:
        return candles_dict

    # 1. M1 (60s x 20 bars)
    try:
        c_m1 = api.get_candles(symbol, 60, 20, now_ts)
        if isinstance(c_m1, list):
            candles_dict["m1"] = c_m1
    except Exception:
        pass

    # 2. M5 (300s x 20 bars)
    try:
        c_m5 = api.get_candles(symbol, 300, 20, now_ts)
        if isinstance(c_m5, list):
            candles_dict["m5"] = c_m5
    except Exception:
        pass

    # 3. M15 (900s x 20 bars)
    try:
        c_m15 = api.get_candles(symbol, 900, 20, now_ts)
        if isinstance(c_m15, list):
            candles_dict["m15"] = c_m15
    except Exception:
        pass

    # 4. Tick / 1s (1s x 30 bars)
    try:
        c_tick = api.get_candles(symbol, 1, 30, now_ts)
        if isinstance(c_tick, list):
            candles_dict["tick"] = c_tick
    except Exception:
        pass

    return candles_dict


def main(silent: bool = False):
    if not silent:
        print("=" * 80)
        print("    IQ OPTION ULTIMATE ALL-IN-ONE ASSET & PAYOUT SCANNER (บอทเช็คตลาด)    ")
        print("=" * 80)

    # 1. Resolve paths
    current_dir = Path(__file__).resolve().parent
    focus_file_path = current_dir / "symbols_user_config.txt"
    if not focus_file_path.is_file():
        raise FileNotFoundError(f"[ERR] ไม่พบไฟล์คอนฟิกคู่เงิน: {focus_file_path}")

    settings_path = current_dir / "settings_filter.json"
    if not settings_path.is_file():
        raise FileNotFoundError(f"[ERR] ไม่พบไฟล์คอนฟิกหลัก: {settings_path}")

    # ล้างไฟล์รายงานตลาดเก่าทั้งหมด เพื่อให้เหลือ symbols_onoff_YYYYMMDD_HHMM.txt เพียง 1 ไฟล์ล่าสุดเสมอตามคำสั่งบอส
    for old_pattern in ["symbols_onoff_*.txt", "symbols_active_*.txt", "active_symbols*.txt"]:
        for old_file in current_dir.glob(old_pattern):
            try:
                old_file.unlink()
            except Exception:
                pass

    # 2. Load focus symbols (SET A & SET B)
    focus_dict = load_focus_symbols(focus_file_path)
    set_a = focus_dict.get("SET_A", [])
    set_b = focus_dict.get("SET_B", [])

    if not set_a and not set_b:
        if not silent:
            print(f"[ERR] ไม่พบรายชื่อคู่เงินใน {focus_file_path.name}")
        return []

    # 3. Connect to IQ Option directly (Standalone)
    try:
        from iqoptionapi.stable_api import IQ_Option
    except ImportError:
        if not silent:
            print("[ERR] iqoptionapi library is not installed.")
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

    if not silent:
        print(f"[CONN] Connecting to IQ Option as {email}...")
    api = IQ_Option(email, password)
    ok, reason = api.connect()
    if not ok:
        if not silent:
            print(f"[ERR] Login failed: {reason}")
        return []
    if not silent:
        print(f"[CONN] Connected successfully! (Balance Mode: {api.get_balance_mode()})")
    time.sleep(1)

    # 4. Fetch market actives & payouts
    if not silent:
        print("[DATA] Scanning market status strictly for 34 Focus Symbols...")

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
    except Exception:
        pass

    all_profits = {}
    for _ in range(3):
        try:
            all_profits = api.get_all_profit()
            if all_profits and len(all_profits) > 0:
                break
            time.sleep(1)
        except Exception:
            time.sleep(1)

    # 5. Scan SET A & SET B strictly (Turbo, Binary, and Digital)
    results_set_a: List[Dict[str, Any]] = [scan_single_symbol(s, all_profits, turbo_actives, binary_actives, api=api) for s in set_a]
    results_set_b: List[Dict[str, Any]] = [scan_single_symbol(s, all_profits, turbo_actives, binary_actives, api=api) for s in set_b]

    # 6. Filter qualifying candidates with Payout >= 84% (Max 12 candidates to evaluate)
    candidates_to_eval = []
    # SET A priority first
    for r in results_set_a:
        if r["binary_tradable"] and len(candidates_to_eval) < 12:
            candidates_to_eval.append(r)
    # Then SET B
    for r in results_set_b:
        if r["binary_tradable"] and len(candidates_to_eval) < 12:
            candidates_to_eval.append(r)

    if not silent:
        print(f"[DATA] พบ {len(candidates_to_eval)} คู่เงินที่ผ่านเกณฑ์ Payout >= {int(MIN_PAYOUT)}% -> ดึงแท่งเทียน 4 TF ส่งให้ secondary_filter.py...")

    # 7. Gateway pulls 4 TF candles for qualifying candidates
    for item in candidates_to_eval:
        sym_to_fetch = item["matched_sym"]
        candles_dict = fetch_multi_tf_candles(api, sym_to_fetch)
        item["candles"] = candles_dict

    # 8. Delegate ranking to secondary_filter.py (7 Skills + 4 Edges + S/R)
    ranked_results = rank_tradable_symbols(candidates_to_eval)

    # Create mapping of scores for reporting
    score_map = {r["symbol"]: r for r in ranked_results}

    # 9. Slice Top `max_symbols` (e.g. 4)
    top_picks: List[str] = []
    for r in ranked_results:
        sym_clean = r["symbol"].replace("-op", "").replace("-OP", "")
        if sym_clean not in top_picks:
            top_picks.append(sym_clean)
        if len(top_picks) >= max_symbols:
            break

    # 10. Build Clean 3D Report (Format exactly matching Boss's template)
    tz_thailand = timezone(timedelta(hours=7))
    now_dt = datetime.now(tz_thailand)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    timestamp_file_str = now_dt.strftime("%Y%m%d_%H%M")

    lines = []
    lines.append("=" * 115)
    lines.append(f"  IQ OPTION 3D FOCUS ASSET SCANNER REPORT (บันทึกเมื่อ: {now_str})")
    lines.append(f"  ตรวจสอบ 34 คู่เงินจาก {focus_file_path.name} ครบ 3 มิติ (Payout >= {int(MIN_PAYOUT)}% + 7 Skills + 4 Edges + S/R)")
    lines.append("=" * 115)

    # Helper function to compute visual display width (handling Thai combining chars and emojis)
    def get_visual_width(text: str) -> int:
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
        current_w = get_visual_width(text)
        return text + (" " * max(0, target_width - current_w))

    def format_pair_line(r: Dict[str, Any]) -> str:
        sym = r["symbol"]
        
        # Binary status with icon (integer percentage e.g. 86%)
        if not r["binary_open"]:
            b_str = "🔴 Binary: ปิด"
        elif r["binary_pct"] >= MIN_PAYOUT:
            b_str = f"🟢 Binary: {int(round(r['binary_pct']))}%"
        else:
            b_str = f"🟡 Binary: {int(round(r['binary_pct']))}%"

        # Turbo status
        t_str = f"⚪ Turbo: {int(round(r['turbo_pct']))}%" if r["turbo_open"] else "⚪ Turbo: ปิด"

        # Digital status
        d_str = f"⚪ Digital: {int(round(r['digital_pct']))}%" if r["digital_open"] else "⚪ Digital: ปิด"

        col_sym = pad_visual(f"  • {sym}", 18)
        col_bin = pad_visual(b_str, 20)
        col_tur = pad_visual(t_str, 20)
        col_dig = pad_visual(d_str, 20)

        return f"{col_sym}| {col_bin}| {col_tur}| {col_dig}"

    # Section SET A
    lines.append(f"\n--- SET A: คู่เงินหลักที่ให้พิจารณาก่อน [{len(set_a)} คู่] ---")
    for r in results_set_a:
        lines.append(format_pair_line(r))

    # Section SET B
    lines.append(f"\n--- SET B: คู่เงินสำรอง [{len(set_b)} คู่] ---")
    for r in results_set_b:
        lines.append(format_pair_line(r))

    # Section Ranked Leaderboard
    if ranked_results:
        lines.append("\n" + "=" * 115)
        lines.append(f"--- ตารางจัดอันดับคู่เงินน่าเทรด (Rank 1 - {len(ranked_results)}) โดย secondary_filter.py ---")
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
    lines.append(f"🏆 สรุปผลคัดเลือก Top {max_symbols} คู่เงินที่ตัดตอนบันทึกลง symbols_trade.json: {', '.join(top_picks) if top_picks else 'ไม่พบคู่ที่ผ่านเกณฑ์'}")
    lines.append("=" * 115)

    output_text = "\n".join(lines)

    # 11. Write symbols_onoff_YYYYMMDD_HHMM.txt inside symbols_scanner (ไฟล์รายงานเพียงไฟล์เดียวตามคำสั่งบอส)
    try:
        # ล้างไฟล์รายงานเก่าทั้งหมดก่อนเขียนไฟล์รอบใหม่ เพื่อคงนโยบาย Single File (เหลือเพียง 1 ไฟล์ล่าสุดเสมอ)
        for old_pattern in ["symbols_onoff_*.txt", "symbols_active_*.txt", "active_symbols*.txt"]:
            for old_f in current_dir.glob(old_pattern):
                try:
                    old_f.unlink()
                except Exception:
                    pass

        report_file = current_dir / f"symbols_onoff_{timestamp_file_str}.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(output_text)

        # 12. Save symbols_trade.json in symbols_scanner/ (Standalone - บันทึกเฉพาะ symbols_trade.json ไม่ส่งออกไปบอท)
        local_trade_symbols_path = current_dir / "symbols_trade.json"
        with open(local_trade_symbols_path, "w", encoding="utf-8") as f:
            json.dump(top_picks, f, indent=2, ensure_ascii=False)

        # ลบไฟล์ symbols.json ที่ตกค้างใน symbols_scanner/ ออกทันที (คงไว้เฉพาะ symbols_trade.json เพียงไฟล์เดียวตามคำสั่งบอส)
        local_symbols_legacy_path = current_dir / "symbols.json"
        if local_symbols_legacy_path.is_file():
            try:
                local_symbols_legacy_path.unlink()
            except Exception:
                pass

        if not silent:
            print(f"[SAVE] บันทึกรายงานสถานะตลาด (1 ไฟล์ล่าสุด) -> {report_file.name}")
            print(f"[SAVE] บันทึก Top {max_symbols} คู่เงินลง symbols_scanner/symbols_trade.json: {top_picks}")
    except Exception as e:
        if not silent:
            print(f"[ERR] Failed to write report/symbols file: {e}")

    # 13. Print Console
    if not silent:
        print("\n" + output_text)
        print(f"\n[OK] คัดกรองและจัดอันดับ Top {max_symbols} คู่เงินเสร็จสมบูรณ์เรียบร้อยค่ะ!")

    return top_picks


if __name__ == "__main__":
    main()
