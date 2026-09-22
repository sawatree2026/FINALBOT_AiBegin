"""
IQ Option Ultimate All-in-One Asset & Market Scanner (บอทเช็ครายการเปิดเทรดสมบูรณ์แบบ)
========================================================================================
รวมระบบตรวจสอบสถานะตลาด 5 มิติ และอัตราผลตอบแทน Payout (%) จากโบรกเกอร์ IQ Option
100% ตรงจาก Server โดยไม่มีการตัดทิ้ง พร้อมระบุช่องทางเทรดที่เปิดรับคำสั่งจริง

- อ่านข้อมูลบัญชีจาก: config_setting/settings.json
- บันทึกรายงานฉบับสมบูรณ์ไปที่: config_setting/active_symbols.txt
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

# Ensure UTF-8 output safely for Windows CMD / PowerShell / IDLE
if sys.platform == "win32":
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def classify_asset(symbol: str) -> str:
    """Classifies symbol into clear market categories."""
    clean_sym = symbol.upper()
    
    # 1. Commodities
    commodities = [
        'COCOA', 'COFFEE', 'COTTON', 'SUGAR', 'URANIUM', 'XAUUSD', 'XAGUSD', 
        'XPDUSD', 'XPTUSD', 'UKOUSD', 'USOUSD', 'XNGUSD', 'XAU', 'XAG'
    ]
    if any(c in clean_sym for c in commodities):
        return "COMMODITIES"
        
    # 2. Indices & ETFs
    indices_keywords = [
        'SPY', 'QQQ', 'DIA', 'IWM', 'GDX', 'XLK', 'XLE', 'XLU', 'XLY', 'SQQQ', 
        'SMH', 'TLT', 'SDS', 'US30', 'GER30', 'UK100', 'JP225', 'AUS200', 'EU50', 
        'FR40', 'US2000', 'USNDAQ100', 'SP35', 'SP500', 'GERMANY30', 'EURO50',
        'FRANCE40', 'JAPAN225', 'HONGKONG33', 'HK33'
    ]
    if any(k in clean_sym for k in indices_keywords):
        return "INDICES_ETFS"
        
    # 3. Crypto
    crypto_keywords = [
        'BTC', 'ETH', 'LTC', 'XRP', 'SOL', 'DASH', 'EOS', 'DOT', 'ARB', 'ATOM', 
        'BONK', 'FLOKI', 'PEPE', 'SHIB', 'RENDER', 'ONDO', 'PYTH', 'TIA', 'SUI', 
        'TAO', 'WLD', 'WIF', 'FET', 'GRT', 'ICP', 'IMX', 'INJ', 'IOTA', 'LINK', 
        'MANA', 'SAND', 'STX', 'TON', 'TRON', 'SATS', 'RONIN', 'SEI', 'JUP', 
        'RAYDIUM', 'PENGU', 'DYDX', 'FARTCOIN', 'LABUBU', 'MELANIA', 'TRUMP'
    ]
    if any(k in clean_sym for k in crypto_keywords):
        return "CRYPTO"
        
    # 4. Forex OTC vs Normal Forex
    if "-OTC" in clean_sym:
        return "FOREX_OTC"
        
    # Standard currencies
    currencies = {
        'USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD', 'THB', 'SGD', 
        'HKD', 'INR', 'MYR', 'IDR', 'PHP', 'VND', 'CNY', 'RUB', 'BRL', 'MXN', 
        'ZAR', 'TRY', 'PLN', 'SEK', 'NOK', 'DKK', 'ARS', 'CLP', 'COP', 'PEN'
    }
    if len(clean_sym) == 6 and clean_sym[:3] in currencies and clean_sym[3:] in currencies:
        return "FOREX"
    if clean_sym.endswith("-OP"):
        return "SPECIAL_OP"
        
    # 5. Stocks
    return "STOCKS"


def main():
    print("=" * 70)
    print("    IQ OPTION ULTIMATE ALL-IN-ONE ASSET & PAYOUT SCANNER (บอทเช็คตลาด)    ")
    print("=" * 70)

    # 1. Resolve paths
    current_dir = Path(__file__).resolve().parent
    settings_path = current_dir / "settings.json"
    if not settings_path.is_file():
        settings_path = current_dir.parent / "config_setting" / "settings.json"

    output_path = current_dir / "active_symbols.txt"

    print(f"[PATH] Settings Path : {settings_path}")
    print(f"[PATH] Output Report : {output_path}")

    if not settings_path.is_file():
        print(f"[ERR] Settings file not found at: {settings_path}")
        return

    # 2. Load credentials
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        account = settings.get("account", {})
        email = account.get("iq_email", "").strip()
        password = account.get("iq_password", "").strip()
        if not email or not password:
            raise ValueError("iq_email or iq_password is missing in settings.json")
    except Exception as e:
        print(f"[ERR] Failed to load credentials: {e}")
        return

    # 3. Connect to IQ Option
    try:
        from iqoptionapi.stable_api import IQ_Option
        import iqoptionapi.constants as OP_code
    except ImportError:
        print("[ERR] iqoptionapi library is not installed.")
        return

    print(f"[CONN] Connecting to IQ Option as {email}...")
    api = IQ_Option(email, password)
    ok, reason = api.connect()
    if not ok:
        print(f"[ERR] Login failed: {reason}")
        return
    print(f"[CONN] Connected successfully! (Balance Mode: {api.get_balance_mode()})")

    time.sleep(1)

    # 4. Fetch market data from broker
    print("[DATA] Scanning all market channels (Turbo, Binary, OTC, Profits)...")
    
    # 4.1 Broker Active States
    init_data = api.get_all_init() or {}
    turbo_actives = init_data.get('result', {}).get('turbo', {}).get('actives', {})
    binary_actives = init_data.get('result', {}).get('binary', {}).get('actives', {})

    # 4.2 Broker Profit Percentages
    all_profits = {}
    for _ in range(3):
        try:
            all_profits = api.get_all_profit()
            if all_profits and len(all_profits) > 0:
                break
            time.sleep(1)
        except Exception:
            time.sleep(1)

    # 5. Compile all symbols dynamically
    all_symbols = list(OP_code.ACTIVES.keys())
    for k in all_profits.keys():
        if k not in all_symbols:
            all_symbols.append(k)

    # Cross-reference every symbol with full multi-market status
    tradable_now: List[Dict[str, Any]] = []
    scheduled_assets: List[Dict[str, Any]] = []
    closed_assets: List[Dict[str, Any]] = []

    categorized_tradable: Dict[str, List[Dict[str, Any]]] = {
        "FOREX": [],
        "FOREX_OTC": [],
        "INDICES_ETFS": [],
        "CRYPTO": [],
        "COMMODITIES": [],
        "STOCKS": [],
        "SPECIAL_OP": []
    }

    for sym in all_symbols:
        p_info = all_profits.get(sym, {})
        turbo_p = p_info.get("turbo") or 0.0
        binary_p = p_info.get("binary") or 0.0

        turbo_open = False
        binary_open = False

        for aid, ainfo in turbo_actives.items():
            name = ainfo.get('name', '').replace('front.', '')
            if name == sym:
                if ainfo.get('enabled') is True and ainfo.get('is_suspended') is False:
                    turbo_open = True
                break

        for aid, ainfo in binary_actives.items():
            name = ainfo.get('name', '').replace('front.', '')
            if name == sym:
                if ainfo.get('enabled') is True and ainfo.get('is_suspended') is False:
                    binary_open = True
                break

        turbo_pct = round(turbo_p * 100.0, 1) if turbo_p > 0 else 0.0
        binary_pct = round(binary_p * 100.0, 1) if binary_p > 0 else 0.0
        max_payout = max(turbo_pct, binary_pct)
        cat = classify_asset(sym)

        is_tradable_now = (turbo_open and turbo_pct > 0) or (binary_open and binary_pct > 0)

        # Determine Best Execution Protocol
        if turbo_open and turbo_pct >= binary_pct and turbo_pct > 0:
            best_route = f"TURBO ({turbo_pct}%)"
        elif binary_open and binary_pct > 0:
            best_route = f"BINARY ({binary_pct}%)"
        else:
            best_route = "ปิดรับคำสั่ง"

        entry = {
            "symbol": sym,
            "category": cat,
            "turbo_pct": turbo_pct,
            "turbo_open": turbo_open,
            "binary_pct": binary_pct,
            "binary_open": binary_open,
            "max_payout": max_payout,
            "is_tradable": is_tradable_now,
            "best_route": best_route
        }

        if is_tradable_now:
            tradable_now.append(entry)
            if cat in categorized_tradable:
                categorized_tradable[cat].append(entry)
            else:
                categorized_tradable["STOCKS"].append(entry)
        elif max_payout > 0:
            scheduled_assets.append(entry)
        else:
            closed_assets.append(entry)

    # Sort tradable assets by highest payout first
    tradable_now.sort(key=lambda x: x["max_payout"], reverse=True)
    for cat in categorized_tradable:
        categorized_tradable[cat].sort(key=lambda x: x["max_payout"], reverse=True)

    tz_thailand = timezone(timedelta(hours=7))
    now_str = datetime.now(tz_thailand).strftime("%Y-%m-%d %H:%M:%S")

    # 6. Build Comprehensive Report
    lines = []
    lines.append("=" * 70)
    lines.append(f"  IQ OPTION ULTIMATE ASSET & MARKET REPORT (ดึงข้อมูลเมื่อ: {now_str})")
    lines.append(f"  สินทรัพย์ทั้งหมดในระบบ: {len(all_symbols)} | 🟢 พร้อมเทรดจริงทันที: {len(tradable_now)} รายการ")
    lines.append("=" * 70)
    lines.append("")

    lines.append("=" * 70)
    lines.append(f"🟢 [หมวดที่ 1] สินทรัพย์ที่เปิดรับออเดอร์จริง 100% ณ วินาทีนี้ ({len(tradable_now)} รายการ):")
    lines.append("=" * 70)

    cat_titles = [
        ("FOREX", "💱 สกุลเงินปกติ (Forex Standard)"),
        ("FOREX_OTC", "🌐 สกุลเงิน OTC (Forex OTC)"),
        ("INDICES_ETFS", "📈 ดัชนีและกองทุน ETF (Indices & ETFs - 24 ชม.)"),
        ("CRYPTO", "🪙 คริปโตเคอเรนซี (Crypto)"),
        ("COMMODITIES", "🛢️ สินค้าโภคภัณฑ์ (Commodities - ทองคำ/น้ำมัน)"),
        ("STOCKS", "🏢 หุ้นสหรัฐฯ (US Stocks)"),
        ("SPECIAL_OP", "⚡ สัญญาอนุพันธ์พิเศษ (Special -op Contracts)")
    ]

    for cat_key, cat_title in cat_titles:
        items = categorized_tradable.get(cat_key, [])
        lines.append(f"\n--- {cat_title} [{len(items)} คู่พร้อมเทรด] ---")
        if not items:
            lines.append("  (ขณะนี้ปิดให้บริการ)")
        else:
            for it in items:
                sym = it["symbol"]
                t_str = f"Turbo: {it['turbo_pct']}%" if it['turbo_open'] else "Turbo: ปิด"
                b_str = f"Binary: {it['binary_pct']}%" if it['binary_open'] else "Binary: ปิด"
                lines.append(f"  • {sym:<18} | {t_str:<13} | {b_str:<14} | ช่องทางแนะนำ: {it['best_route']}")

    lines.append("\n" + "=" * 70)
    lines.append(f"🟡 [หมวดที่ 2] สินทรัพย์ที่มี Payout แต่รอเวลาเปิดตลาด / Suspended ({len(scheduled_assets)} รายการ):")
    lines.append("=" * 70)
    for it in scheduled_assets[:25]:  # แสดงตัวอย่าง 25 รายการแรก
        sym = it["symbol"]
        lines.append(f"  • {sym:<18} | Payout ในระบบ: {it['max_payout']}% | สถานะ: รอเปิดตลาดตามตารางเวลาโบรกเกอร์")
    if len(scheduled_assets) > 25:
        lines.append(f"  ... และอีก {len(scheduled_assets) - 25} รายการ")

    lines.append("\n" + "=" * 70)
    lines.append("📋 JSON Configuration Ready (คัดลอกใส่ settings.json ได้ทันที):")
    lines.append("=" * 70)
    top_picks = [x["symbol"] for x in tradable_now if x["max_payout"] >= 80][:8]
    lines.append('"symbols": ' + json.dumps(top_picks, ensure_ascii=False, indent=2))
    lines.append("")

    output_text = "\n".join(lines)

    # 7. Write to active_symbols.txt
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"[OK] Successfully saved Ultimate Report to: {output_path.name}")
    except Exception as e:
        print(f"[ERR] Failed to write report file: {e}")

    # 8. Print Clean Console Output
    print("\n" + output_text)
    print("\n[OK] Ultimate Market Scanner completed successfully!")


if __name__ == "__main__":
    main()
