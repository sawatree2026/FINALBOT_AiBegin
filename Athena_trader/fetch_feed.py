import sys
import os
import argparse
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import AthenaConfig
from broker_client import AthenaBrokerClient
from indicators import (
    calculate_bb_pct_b,
    calculate_stochastic,
    calculate_ma_crossover,
    calculate_macd,
    calculate_rsi,
    calculate_parabolic_sar,
    detect_euf_levels
)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="EURUSD-OTC")
    parser.add_argument("--tf", type=str, default="S30", choices=["S10", "S30", "M1", "M5"])
    args = parser.parse_args()

    cfg = AthenaConfig.load_from_settings()
    client = AthenaBrokerClient(cfg.iq_email, cfg.iq_password, "DEMO")
    
    if not client.connect():
        print("ERROR: Connection failed")
        sys.exit(1)

    tf_sec = {"S10": 10, "S30": 30, "M1": 60, "M5": 300}.get(args.tf, 30)
    raw_df = client.get_candles(args.symbol, tf_sec, count=100)
    client.disconnect()

    df = calculate_bb_pct_b(raw_df, period=41, std_mult=2.0)
    df = calculate_stochastic(df, k_period=13, d_period=3, smooth_k=10)
    df = calculate_ma_crossover(df, fast_period=3, slow_period=6)
    df = calculate_macd(df, fast=15, slow=35, signal=9)
    df = calculate_rsi(df, period=14)
    df = calculate_parabolic_sar(df, af_step=0.09, af_max=0.04)
    euf = detect_euf_levels(df, lookback=50)

    tail = df.tail(5).copy()
    
    print(f"=== MARKET FEED: {args.symbol} (TF: {args.tf}) ===")
    print(f"S/R Levels: Resistances={euf['resistances']} | Supports={euf['supports']}")
    print("Recent Candles & Indicators:")
    for _, row in tail.iterrows():
        candle_type = "GREEN" if row['close'] > row['open'] else "RED" if row['close'] < row['open'] else "DOJI"
        body = abs(row['close'] - row['open'])
        hl = row['high'] - row['low']
        is_gray = (body / hl < 0.12) if hl > 0 else True
        print(f"Time: {int(row['timestamp'])} | O:{row['open']:.5f} H:{row['high']:.5f} L:{row['low']:.5f} C:{row['close']:.5f} | "
              f"{candle_type} (Gray={is_gray}) | BB%B: {row['bb_pct_b']:.3f} | STO(K/D): {row['sto_k']:.1f}/{row['sto_d']:.1f} | "
              f"MA(3/6): {row['ma_fast_ema']:.5f}/{row['ma_slow_sma']:.5f} | MACD: {row['macd_line']:.6f} | RSI: {row['rsi']:.1f}")

if __name__ == "__main__":
    main()
