import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class TradeSignal:
    action: str             # "CALL", "PUT", "WAIT"
    strategy: str           # "BELIEVE", "AP_V2", "NS_V2", "NONE"
    confidence: float       # 0.0 to 100.0
    expiry_minutes: int     # 1 to 5
    reason: str             # Detailed Thai explanation
    is_valid: bool          # Passes all risk filters

class NemesisStrategyEngine:
    def __init__(self):
        pass

    def is_doji_or_gray(self, row: pd.Series) -> bool:
        hl_range = row['high'] - row['low']
        if hl_range == 0:
            return True
        body = abs(row['close'] - row['open'])
        return (body / hl_range) < 0.12

    def check_sto_tangling(self, df: pd.DataFrame, bars: int = 6) -> bool:
        if len(df) < bars:
            return False
        tail = df.tail(bars)
        diff = tail['sto_k'] - tail['sto_d']
        crosses = np.sum(np.diff(np.sign(diff.fillna(0))) != 0)
        return bool(crosses >= 3)

    def evaluate_believe(self, df: pd.DataFrame, euf_levels: Dict[str, list]) -> TradeSignal:
        if len(df) < 45:
            return TradeSignal("WAIT", "BELIEVE", 0.0, 5, "ข้อมูลแท่งเทียนไม่เพียงพอ (ต้องการอย่างน้อย 45 แท่ง)", False)

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]
        
        # 1. Candlestick Health Filter
        if self.is_doji_or_gray(curr) or self.is_doji_or_gray(prev):
            return TradeSignal("WAIT", "BELIEVE", 0.0, 5, "พบแท่งเทียนสีเทา/โดจิ ตลาดลังเลตามกฎข้อห้าม", False)

        # 2. STO Tangling Filter
        if self.check_sto_tangling(df, bars=6):
            return TradeSignal("WAIT", "BELIEVE", 0.0, 5, "เส้น STO พันกัน (Tangled) ห้ามเข้าออเดอร์", False)

        # 3. Indicator Signals
        bb_pct = curr.get('bb_pct_b', 0.5)
        sto_k = curr.get('sto_k', 50.0)
        sto_d = curr.get('sto_d', 50.0)
        prev_k = prev.get('sto_k', 50.0)
        
        fast_ma = curr.get('ma_fast_ema', 0.0)
        slow_ma = curr.get('ma_slow_sma', 0.0)
        prev_fast_ma = prev.get('ma_fast_ema', 0.0)
        prev_slow_ma = prev.get('ma_slow_sma', 0.0)

        # Check CALL Condition:
        # - BB% touched/near 0 (<= 0.10)
        # - STO from <= 15 hooked up and crossing 50
        # - MA Fast 3 EMA crosses above Slow 6 SMA
        bb_call = bb_pct <= 0.15 or prev.get('bb_pct_b', 1.0) <= 0.05
        sto_call_hook = (prev_k <= 20.0 or prev2.get('sto_k', 50.0) <= 20.0) and (sto_k > prev_k)
        sto_cross_50_call = (prev_k < 50.0 and sto_k >= 48.0) or (sto_k > 50.0 and sto_k > sto_d)
        ma_call_cross = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma

        # Check Resistance block for CALL
        resistances = euf_levels.get("resistances", [])
        grid_blocked_call = False
        curr_price = curr['close']
        for r in resistances:
            if 0 < (r - curr_price) < (curr_price * 0.0003): # very close overhead resistance
                grid_blocked_call = True
                break

        if bb_call and sto_call_hook and (ma_call_cross or (fast_ma > slow_ma and sto_cross_50_call)):
            if grid_blocked_call:
                return TradeSignal("WAIT", "BELIEVE", 40.0, 5, "เข้าเงื่อนไข CALL แต่มีแนวต้าน RG DOWN ขวางหน้า", False)
            conf = 85.0 if (bb_pct <= 0.0 and ma_call_cross) else 75.0
            return TradeSignal("CALL", "BELIEVE", conf, 5, "เข้าเงื่อนไข Believe CALL: BB%แตะแนวล่าง + STO Hook Up เหนือ 10 + MA 3 ตัด MA 6 ขึ้น", True)

        # Check PUT Condition:
        # - BB% touched/near 1 (>= 0.90)
        # - STO from >= 85 hooked down and crossing 50
        # - MA Fast 3 EMA crosses below Slow 6 SMA
        bb_put = bb_pct >= 0.85 or prev.get('bb_pct_b', 0.0) >= 0.95
        sto_put_hook = (prev_k >= 80.0 or prev2.get('sto_k', 50.0) >= 80.0) and (sto_k < prev_k)
        sto_cross_50_put = (prev_k > 50.0 and sto_k <= 52.0) or (sto_k < 50.0 and sto_k < sto_d)
        ma_put_cross = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma

        # Check Support block for PUT
        supports = euf_levels.get("supports", [])
        grid_blocked_put = False
        for s in supports:
            if 0 < (curr_price - s) < (curr_price * 0.0003): # very close support underneath
                grid_blocked_put = True
                break

        if bb_put and sto_put_hook and (ma_put_cross or (fast_ma < slow_ma and sto_cross_50_put)):
            if grid_blocked_put:
                return TradeSignal("WAIT", "BELIEVE", 40.0, 5, "เข้าเงื่อนไข PUT แต่มีแนวรับ GR UP ขวางหน้า", False)
            conf = 85.0 if (bb_pct >= 1.0 and ma_put_cross) else 75.0
            return TradeSignal("PUT", "BELIEVE", conf, 5, "เข้าเงื่อนไข Believe PUT: BB%แตะแนวบน + STO Hook Down ต่ำกว่า 90 + MA 3 ตัด MA 6 ลง", True)

        return TradeSignal("WAIT", "NONE", 0.0, 5, "ยังไม่เข้าครบองค์ประกอบเงื่อนไข", False)

    def evaluate_all(self, df: pd.DataFrame, euf_levels: Dict[str, list]) -> TradeSignal:
        # Primary strategy is Believe (as specified in system architecture and E-book)
        return self.evaluate_believe(df, euf_levels)
