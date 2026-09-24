import sys
import os
import time
import argparse
import logging
from datetime import datetime, timezone, timedelta

# Ensure Athena_trader root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import AthenaConfig
from broker_client import AthenaBrokerClient
from athena_core import AthenaCore
from ipc_bridge import AthenaIPCBridge

# Configure clean logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("AthenaRunner")

def print_banner():
    banner = """
====================================================================
  🏛️  ATHENA TRADER — Automated Nemesis Strategy & Analysis System
  - 100% Standalone (Decoupled from FINALBOT)
  - Strategy: Believe & AP/NS Divergence (Nemesis E-Books V1 & V2)
  - Execution Mode: IQ Option DEMO Account
====================================================================
"""
    print(banner)

def main():
    parser = argparse.ArgumentParser(description="Athena Trader Runner")
    parser.add_argument("--symbol", type=str, default="EURUSD-op,GBPUSD-op,GBPJPY-op,EURJPY-op", help="Target currency pair(s) comma-separated")
    parser.add_argument("--tf", type=str, default="S30", choices=["S10", "S30", "M1", "M5"], help="Candle timeframe")
    parser.add_argument("--amount", type=float, default=None, help="Stake per trade")
    parser.add_argument("--duration", type=int, default=5, help="Expiry duration in minutes (default 5)")
    parser.add_argument("--once", action="store_true", help="Run once for analysis test and exit")
    args = parser.parse_args()

    print_banner()

    # 1. Load Settings
    cfg = AthenaConfig.load_from_settings()
    stake = args.amount if args.amount is not None else cfg.stake_per_trade
    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    tf_seconds = {"S10": 10, "S30": 30, "M1": 60, "M5": 300}.get(args.tf, 30)

    # 2. Connect Broker
    broker = AthenaBrokerClient(
        email=cfg.iq_email,
        password=cfg.iq_password,
        account_type="DEMO"
    )
    if not broker.connect():
        print("❌ ไม่สามารถเชื่อมต่อกับ IQ Option ได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ตหรือข้อมูลบัญชีค่ะ")
        sys.exit(1)

    balance = broker.get_balance()
    print(f"✅ เชื่อมต่อบัญชี DEMO สำเร็จ | ยอดเงินคงเหลือ: ${balance:,.2f}")
    print(f"📊 กำลังเริ่มติดตามตลาด: {', '.join(symbols)} | Timeframe: {args.tf} ({tf_seconds}s) | Stake: ${stake}")

    # 3. Setup Core and IPC Bridge
    ipc = AthenaIPCBridge(BASE_DIR)
    core = AthenaCore(ipc)

    tz_th = timezone(timedelta(hours=7))

    try:
        while True:
            for symbol in symbols:
                # 4. Fetch live candles
                try:
                    df = broker.get_candles(symbol, tf_seconds, count=100)
                except Exception as e:
                    logger.error(f"Error fetching candles for {symbol}: {e}")
                    continue

                # 5. Athena Core Analysis
                signal, market_feed = core.process_and_analyze(symbol, df)
                
                now_str = datetime.now(tz_th).strftime("%H:%M:%S")
                cur_price = market_feed["close_price"]
                ind = market_feed["indicators"]
                
                print(f"[{now_str}] {symbol:<10} | ราคา: {cur_price:.5f} | BB%B: {ind['bb_pct_b']} | STO: {ind['sto_k']:.1f}/{ind['sto_d']:.1f} | MA: {ind['ma_fast_3']:.5f}/{ind['ma_slow_6']:.5f} | {signal.action} ({signal.confidence}%)")
                if signal.action != "WAIT":
                    print(f"  👉 เหตุผล: {signal.reason}")

                # 6. Execute Order if Signal is Active
                if signal.action in ["CALL", "PUT"] and signal.is_valid:
                    print(f"🚀 เอเธน่าส่งคำสั่งซื้อขาย: {signal.action} {symbol} | จำนวน: ${stake} | ระยะเวลา: {signal.expiry_minutes} นาที...")
                    success, order_id, msg = broker.execute_order(
                        symbol=symbol,
                        action=signal.action,
                        amount=stake,
                        duration=signal.expiry_minutes
                    )
                    if success:
                        print(f"  ✅ ส่งคำสั่งสำเร็จ! Order ID: {order_id} ({msg})")
                        trade_record = {
                            "timestamp": int(time.time()),
                            "symbol": symbol,
                            "action": signal.action,
                            "amount": stake,
                            "order_id": order_id,
                            "status": "OPEN",
                            "strategy": signal.strategy,
                            "reason": signal.reason
                        }
                        ipc.log_trade(trade_record)
                    else:
                        print(f"  ⚠️ โบรกเกอร์ปฏิเสธคำสั่ง: {msg}")

                time.sleep(1)

            if args.once:
                print("\n[INFO] เสร็จสิ้นการทดสอบโหมด --once ค่ะ")
                break

            # Wait for next candle cycle
            time.sleep(10)

    except KeyboardInterrupt:
        print("\n🛑 หยุดการทำงานโดยผู้ใช้ (KeyboardInterrupt)")
    finally:
        broker.disconnect()
        print("🔒 ปิดการเชื่อมต่อเรียบร้อยแล้วค่ะ")

if __name__ == "__main__":
    main()
