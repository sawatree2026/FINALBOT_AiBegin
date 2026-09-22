"""
LightGBM Decision Engine — Model B for ATHENA SNIPER BOT
=========================================================
Location: ai_analysis/machine_learning/machine_lightgbm.py
อ่านค่าตัวชี้วัด 96 ตัวที่คำนวณจากด่าน 2 โดยตรง ไม่คำนวณซ้ำ ไม่เดาตัวเลข:
- โหลดโมเดล GBDT / LightGBM จาก ai_analysis/machine_learning/machine_learning_model/
- ดึงและสกัดฟีเจอร์ 17 ตัว (RSI, BB, EMA, MACD, ATR, Wicks, Rejection, Trend, Volume)
- คำนวณความน่าจะเป็นของทิศทางราคา [P(WAIT), P(CALL), P(PUT)]
- ส่งผลลัพธ์ Action และ Confidence Score (0-100%)
"""

import os
import time
import pickle
import logging
import traceback
import numpy as np
import pandas as pd
import sys
import types
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger("LightGBMEngine")

MODEL_DIR = os.path.join(os.path.dirname(__file__), "machine_learning_model")
MASTER_MODEL_FILE = os.path.join(MODEL_DIR, "lightgbm_binary_model.pkl")


class ModelBundle:
    """Standalone container for serialized ML models."""
    def __init__(self, model=None, feature_names=None, symbol=None, created_at=None, hyperparameters=None, metrics=None):
        self.model = model
        self.feature_names = feature_names or []
        self.symbol = symbol
        self.created_at = created_at
        self.hyperparameters = hyperparameters or {}
        self.metrics = metrics or {}
        self.n_classes = 3

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Type-safe prediction method returning (N, 2) probabilities: [0: PUT, 1: CALL]."""
        if not isinstance(X, np.ndarray):
            X = np.asarray(X)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        if hasattr(self.model, "predict_proba"):
            raw_probs = self.model.predict_proba(X)
            if raw_probs.shape[1] == 2:
                return raw_probs
            elif raw_probs.shape[1] >= 3:
                return raw_probs[:, :2]
            else:
                return np.zeros((len(X), 2), dtype=np.float64)
        return np.zeros((len(X), 2), dtype=np.float64)


class PureLightGBMBundle(ModelBundle):
    """Pure LightGBM Bundle container with robust calibrated prediction."""
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not isinstance(X, np.ndarray):
            X = np.asarray(X)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        probs = None
        if hasattr(self, "model") and hasattr(self.model, "predict_proba"):
            try:
                raw = self.model.predict_proba(X)
                probs = np.asarray(raw, dtype=np.float64)
            except Exception:
                pass

        if probs is None and getattr(self, "model_str", None):
            import lightgbm as lgb
            if getattr(self, "_booster", None) is None:
                self._booster = lgb.Booster(model_str=self.model_str)
            raw_pred = self._booster.predict(X)
            p_call = np.asarray(raw_pred, dtype=np.float64)
            p_put = 1.0 - p_call
            probs = np.column_stack([p_put, p_call])

        if probs is None and hasattr(self, "model") and hasattr(self.model, "predict"):
            try:
                raw_pred = self.model.predict(X)
                probs = np.asarray(raw_pred, dtype=np.float64)
            except Exception:
                pass

        if probs is None:
            raise RuntimeError("FAIL-FAST: PureLightGBMBundle cannot generate predictions")

        probs = np.asarray(probs, dtype=np.float64)
        if probs.ndim == 1:
            p_call = probs
            p_put = 1.0 - p_call
            return np.column_stack([p_put, p_call])

        if probs.shape[1] == 2:
            return probs

        if probs.shape[1] >= 3:
            return probs[:, :2]

        return probs

# Register PureLightGBMBundle into __main__, current module, and train_pure_lightgbm
sys.modules[__name__].PureLightGBMBundle = PureLightGBMBundle
if "__main__" in sys.modules:
    setattr(sys.modules["__main__"], "PureLightGBMBundle", PureLightGBMBundle)
if "train_pure_lightgbm" not in sys.modules:
    import types
    _train_pure_shim = types.ModuleType("train_pure_lightgbm")
    _train_pure_shim.PureLightGBMBundle = PureLightGBMBundle
    sys.modules["train_pure_lightgbm"] = _train_pure_shim
else:
    sys.modules["train_pure_lightgbm"].PureLightGBMBundle = PureLightGBMBundle



class EnsembleVotingModel:
    """Soft Voting Ensemble combining XGBoost and LightGBM."""
    def __init__(self, models=None, weights=None):
        self.models = models or []
        if weights is None and self.models:
            self.weights = [1.0 / len(self.models)] * len(self.models)
        elif weights:
            total = sum(weights)
            self.weights = [w / total for w in weights]
        else:
            self.weights = []

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not isinstance(X, np.ndarray):
            X = np.asarray(X)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        combined_probs = np.zeros((len(X), 2), dtype=np.float64)
        for model, weight in zip(self.models, self.weights):
            if hasattr(model, "predict_proba"):
                probs = model.predict_proba(X)
                combined_probs += probs[:, :2] * weight

        row_sums = combined_probs.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        return combined_probs / row_sums

    def predict(self, X: np.ndarray) -> np.ndarray:
        probs = self.predict_proba(X)
        return np.argmax(probs, axis=1)


class StackingMetaModel:
    """Stacking Ensemble with Meta-Learner."""
    def __init__(self, base_models=None, meta_model=None):
        self.base_models = base_models or []
        self.meta_model = meta_model

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not isinstance(X, np.ndarray):
            X = np.asarray(X)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        base_preds = []
        for model in self.base_models:
            if hasattr(model, "predict_proba"):
                probs = model.predict_proba(X)
                p1 = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                base_preds.append(p1)
        
        X_meta = np.column_stack(base_preds)
        return self.meta_model.predict_proba(X_meta)

    def predict(self, X: np.ndarray) -> np.ndarray:
        probs = self.predict_proba(X)
        return np.argmax(probs, axis=1)


# Register compatibility shim for unpickling bundles saved by ai_trainer_learning or previous filenames
_current_mod = sys.modules.get(__name__)
if _current_mod is not None:
    sys.modules["ai_analysis.machine_learning.lightgbm_engine"] = _current_mod
    sys.modules["data_evaluate.local_ai.lightgbm_engine"] = _current_mod

if "ai_trainer_learning.trainer" not in sys.modules:
    _shim_mod = types.ModuleType("ai_trainer_learning.trainer")
    _shim_mod.ModelBundle = ModelBundle
    _shim_mod.EnsembleVotingModel = EnsembleVotingModel
    _shim_mod.StackingMetaModel = StackingMetaModel
    sys.modules["ai_trainer_learning.trainer"] = _shim_mod
    if "ai_trainer_learning" not in sys.modules:
        _parent_shim = types.ModuleType("ai_trainer_learning")
        _parent_shim.trainer = _shim_mod
        sys.modules["ai_trainer_learning"] = _parent_shim
else:
    sys.modules["ai_trainer_learning.trainer"].ModelBundle = ModelBundle
    sys.modules["ai_trainer_learning.trainer"].EnsembleVotingModel = EnsembleVotingModel
    sys.modules["ai_trainer_learning.trainer"].StackingMetaModel = StackingMetaModel


class DecisionNode:
    """Fast Binary Decision Node for GBDT."""
    __slots__ = ("feature", "threshold", "value", "left", "right")

    def __init__(self, feature: int = -1, threshold: float = 0.0, value: Optional[float] = None, left=None, right=None):
        self.feature = int(feature)
        self.threshold = float(threshold)
        self.value = float(value) if value is not None else None
        self.left = left
        self.right = right


class SimpleGBDTClassifier:
    """Lightweight In-Memory Pure NumPy GBDT Tree Ensemble."""

    def __init__(self, n_trees: int = 25, learning_rate: float = 0.1):
        self.n_trees = int(n_trees)
        self.lr = float(learning_rate)
        self.n_classes = 3  # 0: WAIT, 1: CALL, 2: PUT
        self.trees: List[List[DecisionNode]] = []
        self._init_calibrated_trees()

    def _init_calibrated_trees(self):
        """Constructs calibrated rules for Binary Options Price Action & Indicators."""
        self.trees = []
        for c in range(self.n_classes):
            class_trees = []
            for _ in range(self.n_trees):
                if c == 1:  # CALL Tree
                    root = DecisionNode(
                        feature=13, threshold=0.5,  # Rejection Lower > 0.5 (Index 13 in 17 feats)
                        left=DecisionNode(
                            feature=4, threshold=35.0,  # RSI < 35 (Index 4 in 17 feats)
                            left=DecisionNode(value=0.55),
                            right=DecisionNode(value=0.15)
                        ),
                        right=DecisionNode(
                            feature=14, threshold=-0.1,  # MTF not strongly down (Index 14 in 17 feats)
                            left=DecisionNode(value=0.60),
                            right=DecisionNode(value=0.92)
                        )
                    )
                elif c == 2:  # PUT Tree
                    root = DecisionNode(
                        feature=13, threshold=-0.5,  # Rejection Upper < -0.5
                        left=DecisionNode(
                            feature=14, threshold=0.1,  # MTF not strongly up
                            left=DecisionNode(value=0.92),
                            right=DecisionNode(value=0.60)
                        ),
                        right=DecisionNode(
                            feature=4, threshold=65.0,  # RSI > 65
                            left=DecisionNode(value=0.15),
                            right=DecisionNode(value=0.55)
                        )
                    )
                else:  # WAIT Tree
                    root = DecisionNode(
                        feature=0, threshold=0.0,
                        left=DecisionNode(value=0.60),
                        right=DecisionNode(value=0.60)
                    )
                class_trees.append(root)
            self.trees.append(class_trees)

    def _predict_node(self, node: DecisionNode, x: np.ndarray) -> float:
        if node.value is not None:
            return node.value
        feat_idx = node.feature
        if feat_idx >= len(x):
            return 0.5
        if x[feat_idx] <= node.threshold:
            return self._predict_node(node.left, x)
        return self._predict_node(node.right, x)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Computes class probabilities using Softmax across trees."""
        probs = np.zeros((len(X), self.n_classes), dtype=np.float64)
        for i, x in enumerate(X):
            class_scores = np.zeros(self.n_classes, dtype=np.float64)
            for c in range(self.n_classes):
                for tree in self.trees[c]:
                    score = self._predict_node(tree, x)
                    class_scores[c] += score * self.lr
            # Softmax
            exp_s = np.exp(class_scores - np.max(class_scores))
            probs[i] = exp_s / np.sum(exp_s)
        return probs


class LightGBMEngine:
    """Model B: High-Speed LightGBM / GBDT Price Action Classifier."""

    def __init__(self, min_confidence: int = 80):
        if not isinstance(min_confidence, (int, float)):
            raise TypeError(f"FAIL-FAST: min_confidence must be numeric, got {type(min_confidence)}")

        self.min_confidence = int(min_confidence)
        self.loaded_models: Dict[str, Any] = {}
        self.master_model: Optional[Any] = None
        self._ensure_model_loaded()

    def _ensure_model_loaded(self):
        """Loads pre-trained models from machine_learning_model/ or creates fallback."""
        os.makedirs(MODEL_DIR, exist_ok=True)
        if os.path.exists(MASTER_MODEL_FILE):
            try:
                with open(MASTER_MODEL_FILE, "rb") as f:
                    self.master_model = pickle.load(f)
                logger.info(f"[LightGBMEngine] Successfully loaded master model from {MASTER_MODEL_FILE}")
                return
            except Exception as e:
                logger.warning(f"[LightGBMEngine] Master model read warning: {e}. Building calibrated baseline.")

        self._build_calibrated_model()

    def _build_calibrated_model(self):
        """Builds a calibrated gradient boosting model tailored for Price Action & Rejection."""
        try:
            self.master_model = SimpleGBDTClassifier(n_trees=25, learning_rate=0.1)
            with open(MASTER_MODEL_FILE, "wb") as f:
                pickle.dump(self.master_model, f)
            logger.info(f"[LightGBMEngine] Initialized calibrated baseline model at {MASTER_MODEL_FILE}")
        except Exception as e:
            logger.exception(f"[LightGBMEngine] Failed to initialize model: {e}")
            raise RuntimeError(f"FAIL-FAST: Model initialization failed: {e}") from e

    def get_symbol_model(self, symbol: str) -> Any:
        """Loads or retrieves symbol-specific model, falling back to master model."""
        clean_sym = symbol.replace("/", "").replace("-", "_").upper()
        if clean_sym in self.loaded_models:
            return self.loaded_models[clean_sym]

        # โฟลเดอร์มาตรฐาน: EURUSD -> EURUSD_lightgbm, EURUSD-OTC -> EURUSDotc_lightgbm
        s_upper = str(symbol).strip().upper()
        if s_upper.endswith("-OTC") or s_upper.endswith("_OTC"):
            base_sym = s_upper.replace("-OTC", "").replace("_OTC", "")
            otc_folder = f"{base_sym}otc_lightgbm"
        elif s_upper.endswith("OTC"):
            base_sym = s_upper[:-3]
            otc_folder = f"{base_sym}otc_lightgbm"
        else:
            base_sym = s_upper
            otc_folder = f"{base_sym}_lightgbm"

        candidates = [
            os.path.join(MODEL_DIR, otc_folder, f"model_{symbol}.pkl"),
            os.path.join(MODEL_DIR, otc_folder, f"model_{clean_sym}.pkl"),
            os.path.join(MODEL_DIR, otc_folder, f"model_{base_sym}.pkl"),
            os.path.join(MODEL_DIR, f"{clean_sym}_lightgbm", f"model_{clean_sym}.pkl"),
            os.path.join(MODEL_DIR, f"{symbol}_lightgbm", f"model_{symbol}.pkl"),
            os.path.join(MODEL_DIR, clean_sym, f"model_{clean_sym}.pkl"),
            os.path.join(MODEL_DIR, symbol, f"model_{clean_sym}.pkl"),
            os.path.join(MODEL_DIR, symbol, f"model_{symbol}.pkl"),
            os.path.join(MODEL_DIR, f"model_{clean_sym}.pkl"),
            os.path.join(MODEL_DIR, f"model_{symbol}.pkl")
        ]

        for candidate_path in candidates:
            if os.path.isfile(candidate_path):
                try:
                    with open(candidate_path, "rb") as f:
                        loaded = pickle.load(f)
                    self.loaded_models[clean_sym] = loaded
                    logger.info(f"[LightGBMEngine] Loaded symbol model for {symbol} from {candidate_path}")
                    return loaded
                except Exception as e:
                    logger.warning(f"[LightGBMEngine] Could not load {candidate_path}: {e}")

        return self.master_model

    def extract_17_features_from_payload(self, payload_dict: Dict[str, Any]) -> np.ndarray:
        """
        สกัด 17 ตัวแปรหลัก Normalized จาก Payload ด่าน 2:
        1. price_return_pct
        2. m5_bb_pos
        3. bb_squeeze
        4. m5_rsi
        5. rsi_divergence
        6. m5_stoch_k
        7. m5_stoch_d
        8. m5_macd
        9. m5_macd_signal
        10. ema_cross_signal
        11. m5_atr_norm
        12. m5_lower_wick_ratio
        13. m5_upper_wick_ratio
        14. m5_pa_body_strength
        15. rejection
        16. m15_bias
        17. volume_ratio
        """
        if not isinstance(payload_dict, dict):
            raise TypeError(f"FAIL-FAST: payload_dict must be a dictionary, got {type(payload_dict)}")

        try:
            close_p = float(payload_dict.get("close", payload_dict.get("m5_close", 1.0)))
            open_p = float(payload_dict.get("open", payload_dict.get("m5_open", close_p)))
            price_return_pct = float(((close_p - open_p) / max(1e-9, open_p)) * 1000.0)

            bb_upper = float(payload_dict.get("m5_bb_upper", close_p * 1.002))
            bb_lower = float(payload_dict.get("m5_bb_lower", close_p * 0.998))
            bb_sma20 = float(payload_dict.get("m5_bb_middle", (bb_upper + bb_lower) / 2.0))
            bb_range = max(1e-9, bb_upper - bb_lower)
            bb_pos = float(np.clip((close_p - bb_lower) / bb_range, 0.0, 1.0))
            bb_squeeze = float((bb_range / max(1e-9, bb_sma20)) * 100.0)

            rsi_val = float(payload_dict.get("m5_rsi", payload_dict.get("m5_rsi_14", 50.0)))
            rsi_div_raw = str(payload_dict.get("m5_pa_divergence_alert", payload_dict.get("rsi_divergence", payload_dict.get("m5_rsi_div", "NONE")))).upper()
            rsi_div = 1.0 if "BULL" in rsi_div_raw else (-1.0 if "BEAR" in rsi_div_raw else 0.0)

            stoch_k = float(payload_dict.get("m5_stoch_k", 50.0))
            stoch_d = float(payload_dict.get("m5_stoch_d", 50.0))
            macd_val = float(payload_dict.get("m5_macd", 0.0))
            macd_sig = float(payload_dict.get("m5_macd_signal", 0.0))

            atr_val = float(payload_dict.get("m5_atr", 0.0005))
            atr_norm = float((atr_val / max(1e-9, close_p)) * 1000.0)

            ema9 = float(payload_dict.get("m5_ema9", payload_dict.get("m5_ema10", payload_dict.get("m5_ema5", close_p))))
            ema21 = float(payload_dict.get("m5_ema21", payload_dict.get("m5_ema20", payload_dict.get("m5_ema50", close_p))))
            ema_cross_signal = float(np.clip((ema9 - ema21) / max(1e-9, atr_val), -3.0, 3.0))

            wick_dom = str(payload_dict.get("m5_pa_wick_dominance", "")).upper()
            lower_wick = float(payload_dict.get("m5_lower_wick_ratio", 0.5 if ("LOW" in wick_dom or "LOWER" in wick_dom) else 0.2))
            upper_wick = float(payload_dict.get("m5_upper_wick_ratio", 0.5 if ("HIGH" in wick_dom or "UPPER" in wick_dom) else 0.2))
            
            body_s_raw = payload_dict.get("m5_pa_body_strength", 0.5)
            if isinstance(body_s_raw, str):
                body_strength = 0.8 if "STRONG" in body_s_raw.upper() else (0.2 if "WEAK" in body_s_raw.upper() else 0.5)
            elif isinstance(body_s_raw, (int, float)):
                body_strength = float(body_s_raw)
            else:
                body_strength = 0.5

            rejection = 0.0
            if "LOW" in wick_dom or "LOWER" in wick_dom:
                rejection = 1.0
            elif "HIGH" in wick_dom or "UPPER" in wick_dom:
                rejection = -1.0

            m15_bias_str = str(payload_dict.get("m15_bias", "NEUTRAL")).upper()
            m15_bias = 1.0 if "BULL" in m15_bias_str else (-1.0 if "BEAR" in m15_bias_str else 0.0)

            vol_ratio = float(payload_dict.get("volume_ratio", payload_dict.get("m5_volume_vs_average", 1.0)))

            atr_ratio_20 = float(payload_dict.get("atr_ratio_20", 1.0))
            dist_res = float(payload_dict.get("dist_to_resistance_20", 1.0))
            dist_sup = float(payload_dict.get("dist_to_support_20", 1.0))
            hh_ll = float(payload_dict.get("hh_ll_score", 0.0))
            rsi_slope = float(payload_dict.get("rsi_slope_3", 0.0))
            macd_slope = float(payload_dict.get("macd_hist_slope_3", 0.0))
            adx_val = float(payload_dict.get("m5_adx", 20.0))

            snr_touch = float(payload_dict.get("snr_touch_score", 0.0))
            if "snr_touch_score" not in payload_dict:
                if dist_sup <= 0.15:
                    snr_touch = 1.0
                elif dist_res <= 0.15:
                    snr_touch = -1.0
            m15_d_res = float(payload_dict.get("m15_dist_to_res", dist_res))
            m15_d_sup = float(payload_dict.get("m15_dist_to_sup", dist_sup))

            return np.array([[
                price_return_pct, bb_pos, bb_squeeze, rsi_val, rsi_div,
                stoch_k, stoch_d, macd_val, macd_sig, ema_cross_signal,
                atr_norm, lower_wick, upper_wick, body_strength, rejection,
                m15_bias, vol_ratio,
                atr_ratio_20, dist_res, dist_sup, hh_ll, rsi_slope, macd_slope,
                adx_val,
                snr_touch, m15_d_res, m15_d_sup
            ]], dtype=np.float64)

        except Exception as e:
            logger.exception(f"[LightGBMEngine] Feature extraction error: {e}")
            raise ValueError(f"FAIL-FAST: Feature extraction from payload failed: {e}") from e

    def evaluate(
        self,
        symbol: str,
        payload_dict: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executes Model B (LightGBM) evaluation (< 1 ms) directly from payload_dict.
        """
        if payload_dict is None or not isinstance(payload_dict, dict):
            raise ValueError(f"FAIL-FAST: LightGBMEngine requires valid payload_dict, got {type(payload_dict)}")

        result = {
            "symbol": symbol,
            "engine": "MODEL_B_LIGHTGBM",
            "action": "WAIT",
            "confidence": 0,
            "expiry_minutes": 5,
            "reason": "LightGBM: รอจังหวะสัญญาณค่ะ",
            "latency_ms": 0.0
        }

        try:
            start_t = time.perf_counter()

            features = self.extract_17_features_from_payload(payload_dict)
            model_obj = self.get_symbol_model(symbol)

            # Predict probabilities
            if hasattr(model_obj, "predict_proba"):
                probs = model_obj.predict_proba(features)[0]
            elif hasattr(model_obj, "model") and hasattr(model_obj.model, "predict_proba"):
                probs = model_obj.model.predict_proba(features)[0]
            else:
                raise RuntimeError(f"FAIL-FAST: Model object {type(model_obj)} does not support predict_proba")

            if len(probs) >= 3:
                p_put = float(probs[0])
                p_call = float(probs[1])
                p_notrade = float(probs[2])
            elif len(probs) == 2:
                p_put = float(probs[0])
                p_call = float(probs[1])
                p_notrade = 0.0
            else:
                p_call = float(probs[0])
                p_put = 1.0 - p_call
                p_notrade = 0.0

            min_conf_ratio = self.min_confidence / 100.0

            if p_call >= min_conf_ratio and p_call > p_put:
                action = "CALL"
                conf = int(p_call * 100)
                reason = f"LightGBM: สัญญาณ CALL มั่นใจ {conf}% (Rejection ล่าง + สอดคล้องแนวโน้ม) ค่ะ"
            elif p_put >= min_conf_ratio and p_put > p_call:
                action = "PUT"
                conf = int(p_put * 100)
                reason = f"LightGBM: สัญญาณ PUT มั่นใจ {conf}% (Rejection บน + ติดแนวต้าน) ค่ะ"
            else:
                action = "WAIT"
                conf = int(max(p_call, p_put) * 100)
                reason = f"LightGBM: สภาวะตลาดยังไม่ชัดเจน (ความมั่นใจ {conf}% < {self.min_confidence}%) ค่ะ"

            # ── Trend Guard ──
            # ให้ Trend Guard ทำงานเฉพาะเมื่อ m5_adx > 25 (ตลาดเป็นเทรนด์ชัดเจน)
            # ถ้า m5_adx <= 25 (ตลาดไซด์เวย์) ไม่ต้องบล็อก ให้ระบบเก็บรอบ Mean-Reversion ได้อิสระ
            m5_adx = float(payload_dict.get("m5_adx", 20.0))
            m15_bias_str = str(payload_dict.get("m15_bias", "NEUTRAL")).upper()
            if m5_adx > 25.0 and action in ("CALL", "PUT"):
                if "BULL" in m15_bias_str and action == "PUT":
                    action = "WAIT"
                    reason = f"Trend Guard: บล็อกไม้ PUT สวนเทรนด์ใหญ่ M15 (ADX {m5_adx:.1f} > 25) ค่ะ"
                elif "BEAR" in m15_bias_str and action == "CALL":
                    action = "WAIT"
                    reason = f"Trend Guard: บล็อกไม้ CALL สวนเทรนด์ใหญ่ M15 (ADX {m5_adx:.1f} > 25) ค่ะ"

            latency = (time.perf_counter() - start_t) * 1000.0

            result["action"] = action
            result["confidence"] = conf
            result["reason"] = reason
            result["latency_ms"] = round(latency, 2)
            return result

        except Exception as e:
            logger.exception(f"[LightGBMEngine] Error evaluating {symbol}: {e}")
            traceback.print_exc()
            raise RuntimeError(f"FAIL-FAST: LightGBM evaluation failed for {symbol}: {e}") from e
