import pandas as pd
from typing import Dict, Any, Tuple
try:
    from .indicators import (
        calculate_bb_pct_b,
        calculate_stochastic,
        calculate_ma_crossover,
        calculate_macd,
        calculate_rsi,
        calculate_parabolic_sar,
        detect_euf_levels
    )
    from .strategy_nemesis import NemesisStrategyEngine, TradeSignal
    from .ipc_bridge import AthenaIPCBridge
except ImportError:
    from indicators import (
        calculate_bb_pct_b,
        calculate_stochastic,
        calculate_ma_crossover,
        calculate_macd,
        calculate_rsi,
        calculate_parabolic_sar,
        detect_euf_levels
    )
    from strategy_nemesis import NemesisStrategyEngine, TradeSignal
    from ipc_bridge import AthenaIPCBridge

class AthenaCore:
    def __init__(self, ipc_bridge: AthenaIPCBridge = None):
        self.strategy_engine = NemesisStrategyEngine()
        self.ipc = ipc_bridge or AthenaIPCBridge()

    def process_and_analyze(self, symbol: str, raw_df: pd.DataFrame) -> Tuple[TradeSignal, Dict[str, Any]]:
        # 1. Compute Nemesis Technical Indicators
        df = calculate_bb_pct_b(raw_df, period=41, std_mult=2.0)
        df = calculate_stochastic(df, k_period=13, d_period=3, smooth_k=10)
        df = calculate_ma_crossover(df, fast_period=3, slow_period=6)
        df = calculate_macd(df, fast=15, slow=35, signal=9)
        df = calculate_rsi(df, period=14)
        df = calculate_parabolic_sar(df, af_step=0.09, af_max=0.04)
        
        # 2. Detect EUF Price Action (RG DOWN / GR UP)
        euf_levels = detect_euf_levels(df, lookback=50)

        # 3. Analyze Market using Nemesis Strategy Engine
        signal = self.strategy_engine.evaluate_all(df, euf_levels)

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        market_feed = {
            "symbol": symbol,
            "current_time": int(curr['timestamp']),
            "close_price": float(curr['close']),
            "indicators": {
                "bb_pct_b": round(float(curr.get('bb_pct_b', 0.5)), 4),
                "sto_k": round(float(curr.get('sto_k', 50.0)), 2),
                "sto_d": round(float(curr.get('sto_d', 50.0)), 2),
                "prev_sto_k": round(float(prev.get('sto_k', 50.0)), 2),
                "ma_fast_3": round(float(curr.get('ma_fast_ema', 0.0)), 6),
                "ma_slow_6": round(float(curr.get('ma_slow_sma', 0.0)), 6),
                "rsi_14": round(float(curr.get('rsi', 50.0)), 2),
                "macd_line": round(float(curr.get('macd_line', 0.0)), 6),
                "macd_signal": round(float(curr.get('macd_signal', 0.0)), 6)
            },
            "euf_levels": euf_levels,
            "decision": {
                "action": signal.action,
                "strategy": signal.strategy,
                "confidence": signal.confidence,
                "expiry_minutes": signal.expiry_minutes,
                "reason": signal.reason,
                "is_valid": signal.is_valid
            }
        }

        # Publish to IPC Bridge for Decoupled Architecture
        self.ipc.publish_market_feed(market_feed)
        
        # If actionable signal, also publish order command
        if signal.action in ["CALL", "PUT"] and signal.is_valid:
            command = {
                "action": signal.action,
                "symbol": symbol,
                "strategy": signal.strategy,
                "duration": signal.expiry_minutes,
                "reason": signal.reason,
                "timestamp": int(curr['timestamp'])
            }
            self.ipc.publish_order_command(command)

        return signal, market_feed
