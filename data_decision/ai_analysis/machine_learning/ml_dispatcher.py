"""
ML Dispatcher & 17-Feature Extractor for FINALBOT
==================================================
Location: ai_analysis/machine_learning/ml_dispatcher.py
หน้าที่:
1. เปิดอ่านไฟล์ Prompt 99 บรรทัดจากดิสก์ (data_base/output_evaluate/<SYMBOL>/)
2. สกัดและแปลงค่าทุกฟิลด์จากไฟล์ Prompt 99 บรรทัดเป็น Dictionary พร้อมสร้าง standard keys 100%
3. ส่งข้อมูล Dictionary เข้าสู่สมองกล ML (Mode A, Mode B, Mode AB) ผ่าน RAM
4. บันทึกผลลัพธ์ลง CSV Audit และส่งคืน JSON Decision ทันที
"""

import os
import csv
import time
import glob
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from .dual_brain import DualBrainCoordinator, normalize_mode
from .machine_chronos import Chronos2ONNXEngine
from config_setting.config_loader import load_settings
from data_trade.payload_sanitizer import sanitize_payload_text

logger = logging.getLogger("MLDispatcher")

# รายชื่อ 17 ตัวแปรหลักที่ ML ดึงไปใช้จริง
ML_17_FIELDS: List[str] = [
    "close",               # 1. ราคาปิดปัจจุบัน
    "m5_bb_upper",         # 2. กรอบบน Bollinger Bands
    "m5_bb_lower",         # 3. กรอบล่าง Bollinger Bands
    "m5_rsi",              # 4. ค่า RSI (14)
    "m5_stoch_k",          # 5. ค่า Stochastic (%K)
    "m5_stoch_d",          # 6. ค่า Stochastic (%D)
    "m5_macd",             # 7. ค่า MACD
    "m5_atr",              # 8. ค่าความผันผวน ATR (14)
    "m5_lower_wick_ratio", # 9. ความยาวไส้เทียนล่าง
    "m5_upper_wick_ratio", # 10. ความยาวไส้เทียนบน
    "m5_pa_body_strength", # 11. สัดส่วนเนื้อเทียน
    "m15_bias",            # 12. ทิศทางเทรนด์ M15
    "m5_bias",             # 13. ทิศทางเทรนด์ M5
    "mtf_alignment_%",     # 14. ความสอดคล้องเทรนด์ใหญ่
    "m5_support",          # 15. ระดับแนวรับ
    "m5_resistance",       # 16. ระดับแนวต้าน
    "room_to_target"       # 17. ระยะห่างถึงแนวรับ-ต้าน
]


def _to_float(val: Any, default: float = 0.0) -> float:
    """Safe float conversion."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_int(val: Any, default: int = 0) -> int:
    """Safe int conversion."""
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


class MLDispatcher:
    """Master ML Pipeline Dispatcher (Reads disk payload and extracts 17 ML features)."""

    _INSTANCE: Optional["MLDispatcher"] = None
    AI_DECISION_OUTPUT_BASE_DIR = os.path.join("data_base", "output_decision", "ai_decision")

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.settings = config or load_settings(reload=False)
        cfg_ml = self.settings.get("ml_mode", {})
        if not cfg_ml and "ai_mode" in self.settings:
            cfg_ml = self.settings.get("ai_mode", {})

        self.mode = normalize_mode(
            cfg_ml.get("model", cfg_ml.get("ml_model", cfg_ml.get("engine", "DUAL_BRAIN")))
        )
        self.min_confidence = int(cfg_ml.get("min_confidence", 60))
        self.stake = float(self.settings.get("account", {}).get("stake_per_trade", 35.0))
        self.chronos2_engine = None
        if self.mode == "CHRONOS_2_ONNX":
            model_path = cfg_ml.get(
                "chronos2_model_path",
                Chronos2ONNXEngine.DEFAULT_MODEL_PATH
            )
            self.chronos2_engine = Chronos2ONNXEngine(
                model_path=model_path,
                min_confidence=self.min_confidence
            )

        self.coordinator = DualBrainCoordinator(
            mode=self.mode,
            min_confidence=self.min_confidence,
            default_stake=self.stake
        )
        logger.info(f"[MLDispatcher] Initialized | Mode: {self.mode} | Min Conf: {self.min_confidence}%")

    @classmethod
    def get_instance(cls, config: Optional[Dict[str, Any]] = None) -> "MLDispatcher":
        if cls._INSTANCE is None or config is not None:
            cls._INSTANCE = cls(config=config)
        return cls._INSTANCE

    @classmethod
    def get_latest_prompt_file(cls, symbol: str, base_dir: Optional[str] = None) -> str:
        """Finds the most recent 99-line prompt file for the symbol in data_base/evaluate_output/<SYMBOL>/."""
        if base_dir is None:
            cfg = load_settings(reload=False)
            base_dir = cfg.get("data_evaluate", {}).get("output_dir", os.path.join("data_base", "output_evaluate"))
        symbol_dir = os.path.join(base_dir, symbol)
        if not os.path.isdir(symbol_dir):
            raise FileNotFoundError(f"FAIL-FAST: Symbol evaluate output directory not found: {symbol_dir}")
        txt_files = sorted(
            [os.path.join(symbol_dir, f) for f in os.listdir(symbol_dir) if f.endswith('.txt')],
            key=os.path.getmtime
        )
        if not txt_files:
            raise FileNotFoundError(f"FAIL-FAST: No prompt .txt files found in {symbol_dir}")
        return txt_files[-1]

    @staticmethod
    def extract_17_features_from_disk(prompt_filepath: str) -> Dict[str, Any]:
        """
        เปิดไฟล์ Prompt 99 บรรทัดบนดิสก์ สกัดและแปลงค่าทุกฟิลด์เป็น Dictionary พร้อม standard keys
        """
        if not prompt_filepath or not os.path.isfile(prompt_filepath):
            raise FileNotFoundError(f"FAIL-FAST: Payload file not found at {prompt_filepath}")

        raw_data: Dict[str, Any] = {}
        current_tf: Optional[str] = None
        in_ohlcv: bool = False

        with open(prompt_filepath, "r", encoding="utf-8") as f:
            payload_text = f.read()
        payload_text, _ = sanitize_payload_text(payload_text, source=prompt_filepath)
        for line in payload_text.splitlines(keepends=True):
                raw_line = line
                line = line.strip()
                if not line or line.startswith("::") or line.startswith("#") or line.startswith("==="):
                    continue

                if line.startswith("ID:"):
                    p_id = line.split(":", 1)[1].strip()
                    raw_data["ID"] = p_id
                    raw_data["prompt_id"] = p_id
                    continue

                if line.startswith("m1:"):
                    current_tf = "m1"
                    in_ohlcv = False
                    continue
                elif line.startswith("m5:"):
                    current_tf = "m5"
                    in_ohlcv = False
                    continue
                elif line.startswith("m15:"):
                    current_tf = "m15"
                    in_ohlcv = False
                    continue
                elif line.startswith("ohlcv:"):
                    in_ohlcv = True
                    continue
                elif not raw_line.startswith(" ") and not raw_line.startswith("\t") and ":" in line and not line.startswith("ID:"):
                    in_ohlcv = False
                    if not line.startswith("m1") and not line.startswith("m5") and not line.startswith("m15"):
                        current_tf = None

                if ":" in line:
                    parts = line.split(":", 1)
                    k = parts[0].strip()
                    v = parts[1].strip().strip("'\"")
                    if not v:
                        continue

                    if k == "timestamp":
                        raw_data["timestamp"] = v
                        raw_data["prompt_timestamp"] = v

                    # Type conversion
                    val: Any = v
                    if v.lower() == "true":
                        val = True
                    elif v.lower() == "false":
                        val = False
                    else:
                        try:
                            if "." in v or "e" in v.lower():
                                val = float(v)
                            else:
                                val = int(v)
                        except ValueError:
                            val = v

                    # Contextual assignment
                    if in_ohlcv and current_tf:
                        if k.startswith(f"{current_tf}_"):
                            raw_data[k] = val
                            base_k = k[len(f"{current_tf}_"):]
                            if current_tf == "m5":
                                raw_data[base_k] = val
                        else:
                            raw_data[f"{current_tf}_{k}"] = val
                            if current_tf == "m5":
                                raw_data[k] = val
                    else:
                        raw_data[k] = val
                        if k.startswith("mtf_"):
                            raw_data[k[4:]] = val
                        elif k.startswith("m5_") and not in_ohlcv:
                            raw_data[k[3:]] = val

        # Construct and validate standard keys
        features_17: Dict[str, Any] = dict(raw_data)
        if "prompt_id" in raw_data:
            features_17["prompt_id"] = raw_data["prompt_id"]
            features_17["ID"] = raw_data["prompt_id"]
        if "prompt_timestamp" in raw_data:
            features_17["prompt_timestamp"] = raw_data["prompt_timestamp"]
            features_17["timestamp"] = raw_data["prompt_timestamp"]

        # 1. Close & Basic Prices
        close_val = _to_float(features_17.get("close", features_17.get("m5_close", features_17.get("m1_close", 0.0))))
        if close_val <= 0.0:
            raise ValueError(f"FAIL-FAST: Invalid close price ({close_val}) in payload {prompt_filepath}")
        features_17["close"] = close_val
        features_17["m5_close"] = _to_float(features_17.get("m5_close"), close_val)
        features_17["open"] = _to_float(features_17.get("open", features_17.get("m5_open", features_17.get("m1_open"))), close_val)
        features_17["m5_open"] = _to_float(features_17.get("m5_open"), features_17["open"])
        features_17["high"] = _to_float(features_17.get("high", features_17.get("m5_high")), close_val)
        features_17["m5_high"] = _to_float(features_17.get("m5_high"), features_17["high"])
        features_17["low"] = _to_float(features_17.get("low", features_17.get("m5_low")), close_val)
        features_17["m5_low"] = _to_float(features_17.get("m5_low"), features_17["low"])
        features_17["volume"] = _to_int(features_17.get("volume", features_17.get("m5_volume", features_17.get("m1_volume", 0))), 0)
        features_17["m5_volume"] = _to_int(features_17.get("m5_volume"), features_17["volume"])

        # 2. Bollinger Bands
        features_17["m5_bb_upper"] = _to_float(features_17.get("m5_bb_upper"), close_val * 1.002)
        features_17["m5_bb_lower"] = _to_float(features_17.get("m5_bb_lower"), close_val * 0.998)
        features_17["m5_bb_middle"] = _to_float(features_17.get("m5_bb_middle"), (features_17["m5_bb_upper"] + features_17["m5_bb_lower"]) / 2.0)
        features_17["m5_bb_width"] = _to_float(features_17.get("m5_bb_width"), max(1e-9, features_17["m5_bb_upper"] - features_17["m5_bb_lower"]))

        # 3. Oscillators & Indicators
        features_17["m5_rsi"] = _to_float(features_17.get("m5_rsi", features_17.get("m5_rsi_14")), 50.0)
        features_17["m5_stoch_k"] = _to_float(features_17.get("m5_stoch_k"), 50.0)
        features_17["m5_stoch_d"] = _to_float(features_17.get("m5_stoch_d"), 50.0)
        features_17["m5_macd"] = _to_float(features_17.get("m5_macd"), 0.0)
        features_17["m5_macd_signal"] = _to_float(features_17.get("m5_macd_signal"), 0.0)
        features_17["m5_adx"] = _to_float(features_17.get("m5_adx"), 25.0)
        features_17["m5_atr"] = _to_float(features_17.get("m5_atr"), 0.0005)

        # 4. EMAs
        features_17["m5_ema5"] = _to_float(features_17.get("m5_ema5"), close_val)
        features_17["m5_ema10"] = _to_float(features_17.get("m5_ema10"), features_17["m5_ema5"])
        features_17["m5_ema20"] = _to_float(features_17.get("m5_ema20"), features_17["m5_ema10"])
        features_17["m5_ema50"] = _to_float(features_17.get("m5_ema50"), features_17["m5_ema20"])
        features_17["m5_ema9"] = _to_float(features_17.get("m5_ema9"), features_17["m5_ema10"])
        features_17["m5_ema21"] = _to_float(features_17.get("m5_ema21"), features_17["m5_ema20"])

        # 5. Price Action & Wicks
        wick_dom = str(features_17.get("m5_pa_wick_dominance", "")).upper()
        features_17["m5_pa_wick_dominance"] = wick_dom

        candle_range = max(1e-9, features_17["m5_high"] - features_17["m5_low"])
        calc_upper_wick = (features_17["m5_high"] - max(features_17["m5_open"], features_17["m5_close"])) / candle_range
        calc_lower_wick = (min(features_17["m5_open"], features_17["m5_close"]) - features_17["m5_low"]) / candle_range

        features_17["m5_lower_wick_ratio"] = _to_float(features_17.get("m5_lower_wick_ratio"), calc_lower_wick)
        features_17["m5_upper_wick_ratio"] = _to_float(features_17.get("m5_upper_wick_ratio"), calc_upper_wick)
        features_17["m5_pa_body_strength"] = str(features_17.get("m5_pa_body_strength", "MODERATE"))
        features_17["m5_pa_divergence_alert"] = str(features_17.get("m5_pa_divergence_alert", "NONE")).upper()

        # 6. Trend & Support / Resistance
        features_17["m15_bias"] = str(features_17.get("m15_bias", "NEUTRAL")).upper()
        features_17["m5_bias"] = str(features_17.get("m5_bias", "NEUTRAL")).upper()
        features_17["mtf_alignment_%"] = _to_float(features_17.get("mtf_alignment_%"), 50.0)
        features_17["m5_support"] = _to_float(features_17.get("m5_support"), features_17["m5_bb_lower"])
        features_17["m5_resistance"] = _to_float(features_17.get("m5_resistance"), features_17["m5_bb_upper"])
        features_17["m5_pivot"] = _to_float(features_17.get("m5_pivot"), (features_17["m5_high"] + features_17["m5_low"] + features_17["m5_close"]) / 3.0)

        # 7. Volume
        vol_avg = _to_float(features_17.get("m5_volume_vs_average", features_17.get("volume_ratio")), 1.0)
        features_17["m5_volume_vs_average"] = vol_avg
        features_17["volume_ratio"] = vol_avg

        # 8. Room to Target
        features_17["room_to_target"] = _to_float(features_17.get("room_to_target"), features_17["m5_bb_width"])

        return features_17

    @classmethod
    def _enforce_retention_pattern(cls, symbol_dir: str, pattern: str, max_files: int = 30) -> None:
        """Keeps at most max_files in the symbol directory for the specified pattern."""
        try:
            files = sorted(
                glob.glob(os.path.join(symbol_dir, pattern)),
                key=os.path.getmtime
            )
            while len(files) > max_files:
                oldest = files.pop(0)
                try:
                    os.remove(oldest)
                    logger.debug(f"[MLDispatcher] Retention cleanup removed: {oldest}")
                except Exception as e:
                    logger.warning(f"[MLDispatcher] Could not remove old file {oldest}: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"[MLDispatcher] Error during retention cleanup: {e}", exc_info=True)

    @classmethod
    def _save_decision_txt(
        cls,
        symbol: str,
        decision: Dict[str, Any],
        analysis_id: str,
        timestamp_str: str,
        model_mode: str = "DUAL_BRAIN",
        stake: float = 35.0,
        tradeable: bool = False
    ) -> str:
        """
        Saves decision to data_base/ai_decision_output/<SYMBOL>/<ID>.txt
        First line: ID:<ID>
        Structure:
        ID:<ID>
        meta:
          timestamp: '<timestamp>'
          symbol: <symbol>
          engine_used: <engine_used>
          model_mode: <model_mode>
        decision:
          action: <action>
          confidence_score: <conf>
          suggested_expiry_minutes: <exp>
          stake: <stake>
          tradeable: <tradeable>
          reason_th: "<reason_th>"
        Enforces retention of max 30 .txt files per symbol.
        """
        try:
            symbol_dir = os.path.join(cls.AI_DECISION_OUTPUT_BASE_DIR, symbol)
            os.makedirs(symbol_dir, exist_ok=True)
            txt_path = os.path.join(symbol_dir, f"{analysis_id}.txt")

            action = decision.get("action", "WAIT")
            conf = float(decision.get("confidence_score", 0.0))
            expiry = int(decision.get("suggested_expiry_minutes", decision.get("expiry_minutes", 5)))
            engine_used = decision.get("engine_used", f"ML ({model_mode})")
            reason_th = decision.get("reason_th", decision.get("reason", ""))

            safe_reason = reason_th.replace('"', '\\"')
            tradeable_str = "true" if tradeable else "false"

            content = (
                f"ID:{analysis_id}\n"
                f"meta:\n"
                f"  timestamp: '{timestamp_str}'\n"
                f"  symbol: {symbol}\n"
                f"  engine_used: {engine_used}\n"
                f"  model_mode: {model_mode}\n"
                f"decision:\n"
                f"  action: {action}\n"
                f"  confidence_score: {conf}\n"
                f"  suggested_expiry_minutes: {expiry}\n"
                f"  stake: {stake}\n"
                f"  tradeable: {tradeable_str}\n"
                f"  reason_th: \"{safe_reason}\"\n"
            )

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(content)

            cls._enforce_retention_pattern(symbol_dir, "*.txt", max_files=30)
            logger.info(f"[MLDispatcher] Saved AI Order Decision txt to: {txt_path}")
            return txt_path
        except Exception as e:
            logger.error(f"[MLDispatcher] Could not save AI Order Decision txt for {symbol}: {e}", exc_info=True)
            return ""

    @classmethod
    def _save_decision_csv(
        cls,
        symbol: str,
        decision: Dict[str, Any],
        analysis_id: str,
        timestamp_str: str
    ) -> None:
        """Saves audit record to data_base/ai_decision_output/<SYMBOL>/decisions.csv."""
        try:
            symbol_dir = os.path.join(cls.AI_DECISION_OUTPUT_BASE_DIR, symbol)
            os.makedirs(symbol_dir, exist_ok=True)
            csv_path = os.path.join(symbol_dir, "decisions.csv")

            file_exists = os.path.isfile(csv_path)
            fieldnames = [
                "timestamp", "ID", "symbol", "action", "confidence_score",
                "expiry_minutes", "engine_used", "reason_th"
            ]

            row = {
                "timestamp": timestamp_str,
                "ID": analysis_id,
                "symbol": symbol,
                "action": decision.get("action", "WAIT"),
                "confidence_score": decision.get("confidence_score", 0),
                "expiry_minutes": decision.get("expiry_minutes", 5),
                "engine_used": decision.get("engine_used", "ML"),
                "reason_th": decision.get("reason_th", "")
            }

            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as e:
            logger.error(f"[MLDispatcher] Failed to save decision CSV for {symbol}: {e}")

    def process_payload_file(self, symbol: str, prompt_filepath: Optional[str] = None) -> Dict[str, Any]:
        """
        Reads prompt file from disk, extracts all features, runs ML evaluation via RAM, and returns structured decision.
        If prompt_filepath is omitted, resolves to latest prompt file in data_base/evaluate_output/<SYMBOL>/.
        """
        if prompt_filepath is None:
            prompt_filepath = self.get_latest_prompt_file(symbol)

        # 1. เปิดอ่านไฟล์ดิสก์ และดึงเฉพาะฟีเจอร์หลัก
        features_17 = self.extract_17_features_from_disk(prompt_filepath)

        analysis_id = str(features_17.get("prompt_id") or features_17.get("ID") or "")
        if not analysis_id:
            base_fname = os.path.splitext(os.path.basename(prompt_filepath))[0]
            if base_fname:
                analysis_id = base_fname
            else:
                now_utc = datetime.now(timezone.utc)
                clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
                analysis_id = f"{clean_sym}{now_utc.strftime('%m%d%H%M%S')}"

        timestamp_str = str(features_17.get("prompt_timestamp") or features_17.get("timestamp") or "")
        if not timestamp_str or timestamp_str == "0":
            now_utc = datetime.now(timezone.utc)
            timestamp_str = now_utc.isoformat()

        # 2. ส่งข้อมูล Dictionary เข้า ML Coordinator (Mode A, B, หรือ AB) ผ่าน RAM
        if self.mode == "CHRONOS_2_ONNX":
            close_prices = self._load_close_history(symbol, prompt_filepath)
            ml_res = self.chronos2_engine.evaluate(
                symbol=symbol,
                close_prices=close_prices,
                payload_dict=features_17
            )
        else:
            ml_res = self.coordinator.evaluate_symbol(symbol, payload_dict=features_17)

        # 3. จัดโครงสร้างผลการตัดสินใจ
        decision = {
            "symbol": symbol,
            "action": ml_res.get("action", "WAIT"),
            "expiry_minutes": ml_res.get("expiry_minutes", 5),
            "suggested_expiry_minutes": ml_res.get("expiry_minutes", 5),
            "confidence_score": float(ml_res.get("confidence", 0)),
            "engine_used": f"ML ({self.coordinator.mode})",
            "timestamp": timestamp_str,
            "ID": analysis_id,
            "reason_th": ml_res.get("reason", "")
        }

        tradeable = (decision.get("action") in ["CALL", "PUT"]) and (decision.get("confidence_score", 0.0) >= self.min_confidence)

        # 4. บันทึกประวัติลง CSV Audit และ TXT Decision (<ID>.txt)
        self._save_decision_csv(symbol, decision, analysis_id, timestamp_str)
        self._save_decision_txt(
            symbol=symbol,
            decision=decision,
            analysis_id=analysis_id,
            timestamp_str=timestamp_str,
            model_mode=self.mode,
            stake=self.stake,
            tradeable=tradeable
        )

        return decision

    @classmethod
    def _load_close_history(cls, symbol: str, prompt_filepath: str) -> List[float]:
        """Load recent M5 closes emitted by data_feed/data_evaluate."""
        symbol_dir = os.path.dirname(prompt_filepath)
        files = sorted(
            (
                os.path.join(symbol_dir, name)
                for name in os.listdir(symbol_dir)
                if name.endswith(".txt")
            ),
            key=os.path.getmtime
        )
        closes: List[float] = []
        for path in files[-512:]:
            try:
                features = cls.extract_17_features_from_disk(path)
                close = float(features.get("m5_close", features.get("close", 0.0)))
                if close > 0:
                    closes.append(close)
            except (ValueError, TypeError, OSError):
                continue
        if len(closes) < 10:
            raise ValueError(
                f"FAIL-FAST: Chronos-2 requires at least 10 data_feed closes for {symbol}; "
                f"received {len(closes)}"
            )
        return closes
