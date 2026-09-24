import sys
import os
import time
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import AthenaConfig
from broker_client import AthenaBrokerClient

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--action", type=str, required=True, choices=["CALL", "PUT", "call", "put"])
    parser.add_argument("--amount", type=float, default=35.0)
    parser.add_argument("--duration", type=int, default=1)
    args = parser.parse_args()

    cfg = AthenaConfig.load_from_settings()
    client = AthenaBrokerClient(cfg.iq_email, cfg.iq_password, "DEMO")
    
    if not client.connect():
        print("ERROR: Broker connection failed")
        sys.exit(1)

    print(f"Executing {args.action.upper()} on {args.symbol} | Amount: ${args.amount} | Duration: {args.duration} min (DEMO)")
    bal_before = client.get_balance()
    success, order_id, msg = client.execute_order(args.symbol, args.action, args.amount, args.duration)
    
    if not success:
        print(f"FAILED: {msg}")
        client.disconnect()
        sys.exit(1)

    print(f"SUCCESS: Order ID {order_id} placed. Awaiting expiry ({args.duration}m)...")
    
    # Wait for expiry
    wait_seconds = args.duration * 60 + 5
    start_t = time.time()
    while time.time() - start_t < wait_seconds:
        time.sleep(3)

    bal_after = client.get_balance()
    diff = bal_after - (bal_before - args.amount)
    profit = bal_after - bal_before
    outcome = "WIN" if profit > 0 else "LOSS" if profit < 0 else "EQUAL"
    
    print(f"=== TRADE RESULT ===")
    print(f"Outcome: {outcome} | Net Profit: ${profit:,.2f} | Balance Before: ${bal_before:,.2f} | Balance After: ${bal_after:,.2f}")
    client.disconnect()

if __name__ == "__main__":
    main()
