import sys
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import AthenaConfig
from broker_client import AthenaBrokerClient

def scan_high_payout_symbols(min_payout: int = 85):
    cfg = AthenaConfig.load_from_settings()
    client = AthenaBrokerClient(cfg.iq_email, cfg.iq_password, "DEMO")
    
    if not client.connect():
        print("ERROR: Connection failed")
        return []

    # Get payout data from IQ Option API
    try:
        turbo_init = client.api.get_all_init().get("turbo", {}).get("actives", {})
        binary_init = client.api.get_all_init().get("binary", {}).get("actives", {})
        
        # Also check current profit commission
        payouts = {}
        for active_id, data in turbo_init.items():
            name = data.get("name", "").replace("front.", "")
            enabled = data.get("enabled", False)
            if enabled and name:
                try:
                    pay = 100 - client.api.get_commission_change(active_id)
                    if pay >= min_payout:
                        payouts[name] = pay
                except Exception:
                    pass
                    
        # Check binary profit
        all_profit = client.api.get_all_profit()
        for name, profit_data in all_profit.items():
            turbo_p = int(profit_data.get("turbo", 0) * 100)
            binary_p = int(profit_data.get("binary", 0) * 100)
            best_p = max(turbo_p, binary_p)
            if best_p >= min_payout:
                payouts[name] = max(payouts.get(name, 0), best_p)

        # Sort by payout descending
        sorted_symbols = sorted(payouts.items(), key=lambda x: x[1], reverse=True)
        print(f"=== FOUND {len(sorted_symbols)} ASSETS WITH PAYOUT >= {min_payout}% ===")
        for s, p in sorted_symbols:
            print(f"Asset: {s:<15} | Payout: {p}%")
            
        client.disconnect()
        return [s for s, _ in sorted_symbols]
    except Exception as e:
        print(f"Error querying payouts: {e}")
        client.disconnect()
        return []

if __name__ == "__main__":
    scan_high_payout_symbols(85)
