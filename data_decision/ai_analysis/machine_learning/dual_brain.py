"""
Dual-Brain Master Coordinator — Local AI Core for ATHENA SNIPER BOT
====================================================================
Location: ai_analysis/machine_learning/dual_brain.py
Manages Multi-Engine Decision Flow (100% In-Memory):
- Mode 'CHRONOS'   : Amazon Chronos Time-Series Quantile Forecaster
- Mode 'LIGHTGBM'  : LightGBM Multi-Timeframe Price Action Classifier
- Mode 'DUAL_BRAIN': Dual-Brain Ensemble (LightGBM 1st Gate -> Chronos 2nd Gate)
Outputs standardized A+ Sniper Action Payload to Part 3 Execution Gate.
"""

import time
import logging
import concurrent.futures
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple

from .machine_chronos import ChronosEngine
from .machine_lightgbm import LightGBMEngine

logger = logging.getLogger("DualBrainCoordinator")


def normalize_mode(mode_str: str) -> str:
    """
    Normalize various model mode names into standardized internal names:
    - DUAL_BRAIN, DUAL_BRAIN_AB, LIGHTGBM_CHRONOS, CASCADE, AB, DUAL -> DUAL_BRAIN
    - LIGHTGBM, LIGHTGBM_ONLY, B, GBM -> LIGHTGBM
    - CHRONOS, CHRONOS_ONLY, A -> CHRONOS
    - Default: DUAL_BRAIN
    """
    if not mode_str:
        return "DUAL_BRAIN"

    clean = str(mode_str).strip().upper()
    if clean in ("CHRONOS_2_ONNX", "CHRONOS2", "CHRONOS_2"):
        return "CHRONOS_2_ONNX"
    if clean in ("DUAL_BRAIN", "DUAL_BRAIN_AB", "LIGHTGBM_CHRONOS", "CASCADE", "AB", "DUAL"):
        return "DUAL_BRAIN"
    elif clean in ("LIGHTGBM", "LIGHTGBM_ONLY", "B", "GBM"):
        return "LIGHTGBM"
    elif clean in ("CHRONOS", "CHRONOS_ONLY", "A"):
        return "CHRONOS"
    return "DUAL_BRAIN"


class DualBrainCoordinator:
    """Master In-Memory AI Coordinator supporting DUAL_BRAIN, LIGHTGBM, and CHRONOS modes."""

    def __init__(self, mode: str = "DUAL_BRAIN", min_confidence: int = 80, default_stake: float = 35.0):
        self.mode = normalize_mode(mode)
        self.min_confidence = int(min_confidence)
        self.default_stake = float(default_stake)

        logger.info(f"[DualBrainCoordinator] Initializing Engines for Mode '{self.mode}'...")
        self.engine_a = ChronosEngine(min_confidence=self.min_confidence)
        self.engine_b = LightGBMEngine(min_confidence=self.min_confidence)
        logger.info(f"[DualBrainCoordinator] Ready | Mode: {self.mode} | Min Conf: {self.min_confidence}% | Stake: {self.default_stake} THB")

    def set_mode(self, mode: str):
        """Dynamically switch mode."""
        self.mode = normalize_mode(mode)
        logger.info(f"[DualBrainCoordinator] Switched mode to: {self.mode}")

    def evaluate_symbol(
        self,
        symbol: str,
        payload_dict: Optional[Dict[str, Any]] = None,
        candles: Optional[Dict[str, pd.DataFrame]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Evaluates a single symbol according to active mode ('DUAL_BRAIN', 'LIGHTGBM', or 'CHRONOS').
        Returns: Standardized Athena Action JSON.
        """
        start_t = time.perf_counter()

        latest_close = 0.0
        if payload_dict and isinstance(payload_dict, dict):
            latest_close = float(payload_dict.get("close", payload_dict.get("m5_close", 0.0)))
        elif isinstance(candles, dict) and "M5" in candles:
            df_m5 = candles.get("M5")
            if df_m5 is not None and not df_m5.empty:
                latest_close = float(df_m5["close"].iloc[-1])

        base_res = {
            "symbol": symbol,
            "action": "WAIT",
            "expiry_minutes": 5,
            "stake": self.default_stake,
            "confidence": 0,
            "strategy": f"LOCAL_AI_{self.mode}",
            "reason": "รอจังหวะสัญญาณค่ะ",
            "m5_close": latest_close,
            "mode": self.mode,
            "details": {}
        }

        # ── 1. Mode CHRONOS: Chronos Only ─────────────────────────────────────
        if self.mode == "CHRONOS":
            res_a = self.engine_a.evaluate(symbol, payload_dict=payload_dict, candles=candles, **kwargs)
            base_res["action"] = res_a.get("action", "WAIT")
            base_res["confidence"] = res_a.get("confidence", 0)
            base_res["reason"] = res_a.get("reason", "")
            base_res["strategy"] = f"CHRONOS_{base_res['action']}"
            base_res["details"] = {"engine_a": res_a}
            base_res["latency_ms"] = round((time.perf_counter() - start_t) * 1000.0, 2)
            return base_res

        # ── 2. Mode LIGHTGBM: LightGBM Only ────────────────────────────────────
        if self.mode == "LIGHTGBM":
            res_b = self.engine_b.evaluate(symbol, payload_dict=payload_dict, **kwargs)
            base_res["action"] = res_b.get("action", "WAIT")
            base_res["confidence"] = res_b.get("confidence", 0)
            base_res["reason"] = res_b.get("reason", "")
            base_res["strategy"] = f"LIGHTGBM_{base_res['action']}"
            base_res["details"] = {"engine_b": res_b}
            base_res["latency_ms"] = round((time.perf_counter() - start_t) * 1000.0, 2)
            return base_res

        # ── 3. Mode DUAL_BRAIN: Cascade Ensemble (LightGBM 1st Gate -> Chronos 2nd Gate) ─
        # ขั้นตอนที่ 1 (LightGBM ด่านที่ 1): รัน LightGBM เพื่อคัดกรองสัญญาณ
        res_b = self.engine_b.evaluate(symbol, payload_dict=payload_dict, **kwargs)
        act_b = res_b.get("action", "WAIT")
        conf_b = res_b.get("confidence", 0)

        # กรณีที่ 1 (GBM สั่ง WAIT หรือความมั่นใจไม่ถึงเกณฑ์): ปัดตกทันที ไม่ต้องรัน Chronos
        if act_b not in ("CALL", "PUT") or act_b == "WAIT" or conf_b < self.min_confidence:
            base_res["action"] = "WAIT"
            base_res["confidence"] = conf_b
            base_res["strategy"] = "DUAL_BRAIN_WAIT"
            base_res["reason"] = "Dual-Brain [LightGBM + Chronos] (ด่าน 1): LightGBM สั่ง WAIT ปัดตกทันทีค่ะ"
            base_res["details"] = {"engine_b": res_b}
            base_res["latency_ms"] = round((time.perf_counter() - start_t) * 1000.0, 2)
            return base_res

        # ขั้นตอนที่ 2 (Chronos ด่านที่ 2 - ยืนยัน): เมื่อ LightGBM ผ่าน (CALL/PUT) ส่งต่อให้ Chronos
        res_a = self.engine_a.evaluate(symbol, payload_dict=payload_dict, candles=candles, **kwargs)
        act_a = res_a.get("action", "WAIT")
        conf_a = res_a.get("confidence", 0)

        base_res["details"] = {"engine_b": res_b, "engine_a": res_a}

        # กรณีที่ 2.1 (Chronos สั่ง WAIT หรือเห็นต่าง): ปัดตกเนื่องจาก Chronos ปฏิเสธ
        if act_a == "WAIT" or act_a != act_b:
            base_res["action"] = "WAIT"
            base_res["confidence"] = max(conf_a, conf_b)
            base_res["strategy"] = "DUAL_BRAIN_WAIT"
            base_res["reason"] = f"Dual-Brain [LightGBM + Chronos] (ด่าน 2): LightGBM ให้ {act_b} แต่ Chronos ปฏิเสธ ({act_a}) ➡️ ปัดตกเป็น WAIT ค่ะ"
            base_res["latency_ms"] = round((time.perf_counter() - start_t) * 1000.0, 2)
            return base_res

        # กรณีที่ 2.2 (ทั้งสองเห็นพ้องตรงกัน 100%): อนุมัติสัญญาณ
        combined_conf = int((conf_a + conf_b) / 2.0)
        if combined_conf >= self.min_confidence:
            base_res["action"] = act_a
            base_res["confidence"] = combined_conf
            base_res["strategy"] = f"DUAL_BRAIN_{act_a}"
            base_res["reason"] = (
                f"👑 Dual-Brain [LightGBM + Chronos] เห็นพ้องตรงกัน: {act_a} "
                f"(Chronos: {conf_a}% + LightGBM: {conf_b}% ➡️ เฉลี่ย {combined_conf}%) ค่ะ"
            )
        else:
            base_res["action"] = "WAIT"
            base_res["confidence"] = combined_conf
            base_res["strategy"] = "DUAL_BRAIN_WAIT"
            base_res["reason"] = (
                f"Dual-Brain [LightGBM + Chronos]: ทิศทางตรงกัน ({act_a}) แต่ความมั่นใจเฉลี่ย {combined_conf}% "
                f"ยังไม่ถึงเกณฑ์ A+ ({self.min_confidence}%) ค่ะ"
            )

        base_res["latency_ms"] = round((time.perf_counter() - start_t) * 1000.0, 2)
        return base_res

    def evaluate_all(self, symbols_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Evaluates multiple symbols concurrently in RAM (< 10 ms)."""
        decisions: List[Dict[str, Any]] = []
        if not symbols_data:
            return decisions

        max_workers = max(1, min(len(symbols_data), 8))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="DualBrainWorker") as executor:
            future_to_sym = {}
            for sym, data in symbols_data.items():
                if isinstance(data, dict) and ("close" in data or "m5_close" in data or "m5_bb_upper" in data):
                    future_to_sym[executor.submit(self.evaluate_symbol, sym, payload_dict=data)] = sym
                elif isinstance(data, dict) and "M5" in data:
                    future_to_sym[executor.submit(self.evaluate_symbol, sym, candles=data)] = sym
                else:
                    future_to_sym[executor.submit(self.evaluate_symbol, sym, payload_dict=data if isinstance(data, dict) else None)] = sym

            for future in concurrent.futures.as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    res = future.result()
                    decisions.append(res)
                except Exception as e:
                    logger.exception(f"[DualBrainCoordinator] Exception evaluating {sym}: {e}")

        decisions.sort(key=lambda d: d.get("confidence", 0), reverse=True)
        return decisions
