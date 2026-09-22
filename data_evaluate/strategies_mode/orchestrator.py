"""
Orchestrator — Central Analysis Pipeline for FINALBOT

Flow per cycle:
    0. Handle OTC Volume (force 1.0)
    1. indicator_store.py -> Basic Indicators
    2. advanced_tools_manager.py -> Advanced Tools
    3. Run 5 Tier-1 engines in parallel
    4. market_state_classifier.py -> Classify state
    5. Save raw OHLCV to CSV
    6. Return full payload
"""

import logging
import concurrent.futures
import pandas as pd
import numpy as np
import os
import csv
import json
import yaml
import traceback
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

from monitoring.console_dashboard import ConsoleUI
from data_evaluate.strategies_mode.orchestration.indicator_store.indicator_store import store
from data_evaluate.strategies_mode.orchestration.advanced_tools.advanced_tools_manager import AdvancedToolsManager

from types import SimpleNamespace
# Import 5 Engines and Classifier
from data_evaluate.strategies_mode.orchestration.market_classifier.trend_engine import TrendEngine
from data_evaluate.strategies_mode.orchestration.market_classifier.strength_engine import StrengthEngine
from data_evaluate.strategies_mode.orchestration.market_classifier.volatility_engine import VolatilityEngine
from data_evaluate.strategies_mode.orchestration.market_classifier.structure_engine import StructureEngine
from data_evaluate.strategies_mode.orchestration.market_classifier.mtf_engine import MTFEngine
from data_evaluate.strategies_mode.orchestration.market_classifier.market_state_classifier import MarketStateClassifier

# Import Supplementary Engines
from data_evaluate.strategies_mode.orchestration.explainability_engine import ExplainabilityEngine
from data_evaluate.strategies_mode.orchestration.liquidity_engine import LiquidityEngine
from data_evaluate.strategies_mode.orchestration.noise_detector import NoiseDetector
from data_evaluate.strategies_mode.orchestration.probability_estimator import ProbabilityEstimator
from data_evaluate.strategies_mode.orchestration.signal_throttle import SignalThrottle
from data_evaluate.strategies_mode.orchestration.context_synthesizer import ContextSynthesizer

from data_evaluate.strategies_mode.orchestration.market_classifier.market_structure_engine import MarketStructureEngine
from data_evaluate.strategies_mode.orchestration.market_classifier.market_pressure_analyzer import MarketPressureAnalyzer
from data_evaluate.strategies_mode.news_calendar import ensure_calendar_news, check_news_impact

logger = logging.getLogger("Orchestrator")


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy data types"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return super(NumpyEncoder, self).default(obj)


class Orchestrator:
    def __init__(self, trade_logger=None, config: Optional[Dict[str, Any]] = None):
        if isinstance(trade_logger, dict) and config is None:
            config = trade_logger
            self.trade_logger = None
        else:
            self.trade_logger = trade_logger
        self.advanced_tools = AdvancedToolsManager()
        
        # ── Tier-1 engines ────────────
        self.trend_engine = TrendEngine()
        self.strength_engine = StrengthEngine()
        self.volatility_engine = VolatilityEngine()
        self.structure_engine = StructureEngine()
        self.mtf_engine = MTFEngine()

        # ── Supplementary Modules ──────────────────────────────────────
        self.explainability_engine = ExplainabilityEngine()
        self.liquidity_engine = LiquidityEngine()
        self.noise_detector = NoiseDetector()
        self.probability_estimator = ProbabilityEstimator()
        self.signal_throttle = SignalThrottle()
        self.context_synthesizer = ContextSynthesizer()
        self.market_structure_engine = MarketStructureEngine()
        self.market_pressure_analyzer = MarketPressureAnalyzer()

        # ── Tier-2 classifier ────────────────────────────────────────────
        self.classifier: Optional[MarketStateClassifier] = None
        self.enable_txt_export: bool = False
        try:
            from config_setting.config_loader import load_settings
            _all_cfg = config or load_settings(reload=False)
            self.config = _all_cfg
            self.enable_txt_export = bool(_all_cfg.get("data_evaluate", {}).get("enable_txt_export", False))
            _cfg = _all_cfg.get("thresholds", {})
            self.classifier = MarketStateClassifier(config=_cfg)
            logger.info(f"MarketStateClassifier initialised (enable_txt_export={self.enable_txt_export})")
        except Exception as e:
            raise

        self.orchestrator_log_dir = _all_cfg.get("data_evaluate", {}).get("output_dir", os.path.join("data_base", "output_evaluate"))
        os.makedirs(self.orchestrator_log_dir, exist_ok=True)

        # ── News Calendar (Part 2 Commander of News Calendar) ───────────
        try:
            ensure_calendar_news(show_ui=True)
            logger.info("News calendar verified and exported to data_evaluate/orchestration by Orchestrator")
        except Exception as e:
            logger.exception(f"Failed to ensure economic news calendar in Orchestrator: {e}")
            raise

        self.ai_memory = []
        self.last_payload = None
        self.latest_payloads: Dict[str, dict] = {}

    def update_ai_memory(self, symbol: str, action: str, reason: str):
        self.ai_memory.append({
            'symbol': symbol,
            'action': action,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
        if len(self.ai_memory) > 5:
            self.ai_memory.pop(0)

    def evaluate_cycle(self, symbols: List[str]) -> None:
        """
        Commander method: Evaluate all symbols concurrently from disk CSV.
        Reads CSV, computes indicators & 5 engines, writes 100-line prompt payload,
        and displays export summary on Console UI.
        """
        if not isinstance(symbols, list):
            raise TypeError(f"FAIL-FAST: symbols must be a list of strings, got {type(symbols).__name__}")
        for sym in symbols:
            if not isinstance(sym, str):
                raise TypeError(f"FAIL-FAST: symbol must be a string, got {type(sym).__name__}")

        ready_symbols: List[str] = []
        failed_symbols: List[str] = []
        max_workers = max(1, min(len(symbols), 20))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Part2EvalWorker") as executor:
            future_to_sym = {
                executor.submit(self.process_cycle, symbol=sym): sym
                for sym in symbols
            }
            for future in concurrent.futures.as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    result = future.result()
                    if isinstance(result, dict):
                        fp = result.get('txt_filepath')
                        ready_symbols.append(sym)
                    elif isinstance(result, str) and os.path.isfile(result):
                        ready_symbols.append(sym)
                    elif result is not None:
                        ready_symbols.append(sym)
                    else:
                        failed_symbols.append(sym)
                        logger.warning(f"[Orchestrator] Evaluation for {sym} returned None")
                except Exception as e:
                    failed_symbols.append(sym)
                    logger.exception(f"[Orchestrator] Evaluation failed for {sym}: {e}")

        # Display Payload Export summary on Console UI
        ConsoleUI.show_payload_export(ready_symbols, failed_symbols)

        # Part 3 reads the persisted payload files independently from SSD.

    def process_cycle(
        self,
        symbol: str,
        ai_context: Optional[Any] = None,
        candles_dict: Optional[Dict[str, pd.DataFrame]] = None,
        news_impact: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if candles_dict is not None:
            raise ValueError(
                "FAIL-FAST: Part 1 -> Part 2 candle transfer through RAM is prohibited; "
                "process_cycle must read CSV files from data_base/output_feed"
            )
        
        # Load directly from CSV files on disk if candles_dict is not provided (Decoupled Part 1 -> Part 2)
        from config_setting.config_loader import get_csv_manager_config
        base_dir = get_csv_manager_config().get("base_dir", os.path.join("data_base", "output_feed"))
        candles_dict = {}
        for tf in ["S30", "M1", "M5"]:
            file_path = os.path.join(base_dir, symbol, f"{symbol}_{tf}.csv")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"FAIL-FAST: CSV file not found for {symbol} {tf} at {file_path}")
                
            df_tf = pd.read_csv(file_path)
            if df_tf is None or df_tf.empty:
                raise ValueError(f"FAIL-FAST: Empty CSV file for {symbol} {tf} at {file_path}")
                
            if 'timestamp' in df_tf.columns:
                df_tf['timestamp'] = pd.to_datetime(df_tf['timestamp'], utc=True)
                df_tf.set_index('timestamp', drop=False, inplace=True)
            elif not isinstance(df_tf.index, pd.DatetimeIndex):
                df_tf.index = pd.to_datetime(df_tf.index, utc=True)
                
            df_tf.sort_index(ascending=True, inplace=True)
            age_seconds = (pd.Timestamp.now(tz="UTC") - df_tf.index[-1]).total_seconds()
            max_age = {"S30": 120, "M1": 180, "M5": 600}[tf]
            if age_seconds > max_age:
                raise ValueError(
                    f"FAIL-FAST: Stale {tf} CSV for {symbol}: age={age_seconds:.1f}s > {max_age}s"
                )
            candles_dict[tf] = df_tf

        if not isinstance(candles_dict, dict):
            raise TypeError(f"FAIL-FAST: candles_dict must be provided as a dictionary for {symbol}")
            
        for tf in ["S30", "M1", "M5"]:
            if tf not in candles_dict or candles_dict[tf] is None or candles_dict[tf].empty:
                raise ValueError(f"FAIL-FAST: Missing or empty {tf} data for {symbol}")
                
        # Warm-up Candle Lookback Check (Fail-Fast) - 250 candles per timeframe
        min_required_candles = {
            'S30': 250,
            'M1': 250,
            'M5': 250,
        }
        for tf, min_req in min_required_candles.items():
            df_tf = candles_dict.get(tf)
            if df_tf is None or len(df_tf) < min_req:
                raise ValueError(f"FAIL-FAST: Insufficient {tf} warm-up candles on disk (got {len(df_tf) if df_tf is not None else 0}, minimum {min_req} required)")

        final_payload = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat()
        }
        s30_last = candles_dict['S30'].iloc[-1]
        final_payload['s30'] = {
            'open': float(s30_last['open']),
            'high': float(s30_last['high']),
            'low': float(s30_last['low']),
            'close': float(s30_last['close']),
            'volume': float(s30_last.get('volume', 0.0) or 0.0),
        }
        final_payload['s30'].update(self._calculate_believe_indicators(candles_dict['S30']))
        # ── 0.1 Timeframe Synchronization (REMOVED) ───────────────────────
        # Note: Timeframe sync is strictly prohibited in Part 2 per specs.
        # Strategies mode evaluates only the independent S30, M1 and M5 inputs.


        # ── 0. Handle OTC Volume ────────────────────────────────────────
        is_otc = "OTC" in symbol.upper()
        if is_otc:
            candles_dict = {k: v.copy() for k, v in candles_dict.items()}
            for tf in ['S30', 'M1', 'M5']:
                if tf in candles_dict and not candles_dict[tf].empty:
                    # Modify in place safely
                    candles_dict[tf].loc[:, 'volume'] = 1.0

        # ── 1. Save OHLCV CSV ───────────────────────────────────────────
        # ย้ายไปเซฟตอนจบ process_cycle เพื่อให้ได้ข้อมูลครบทุกตัว

        # ── 2. Basic Indicators (indicator_store.py) ────────────────────
        try:
            store.calculate_all(symbol, candles_dict, forming_data=None)
            basic_payload = store.get_payload(symbol)
            final_payload.update(basic_payload) # merge m1, m5, ohlcv
        except Exception as e:
            raise

        # ── 3. Advanced Tools ───────────────────────────────────────────
        try:
            df_m5 = candles_dict['M5']
            if isinstance(df_m5, pd.DataFrame) and not df_m5.empty:
                advanced_data = self.advanced_tools.analyze_all(symbol, basic_payload, df_m5)
                final_payload.update(advanced_data)
                final_payload['m5'] = advanced_data['m5']
                final_payload['price_action'] = advanced_data['price_action']
                final_payload['advanced_signals'] = advanced_data['advanced_signals']
        except Exception as e:
            raise

        # ── 4. 5 Engines in parallel ────────────────────────────────────
        try:
            # Zero Tolerance validation before running engines
            if not candles_dict:
                raise ValueError("FAIL-FAST: Missing candles_dict for engine execution")
            for tf in ['S30', 'M1', 'M5']:
                if tf not in candles_dict or candles_dict[tf] is None or candles_dict[tf].empty:
                    raise ValueError(f"FAIL-FAST: Invalid {tf} data in candles_dict")
                if len(candles_dict[tf]) < 50:
                    raise ValueError(f"FAIL-FAST: Insufficient {tf} candles (minimum 50 required)")
            
            # Validate basic payload structure
            required_payload_fields = ['m5', 'm1', 'ohlcv', 'price_action']
            for field in required_payload_fields:
                if field not in final_payload or final_payload[field] is None:
                    raise ValueError(f"FAIL-FAST: Missing required payload field: {field}")
            
            trend_data, strength_data, volatility_data, structure_data, mtf_data = \
                self._run_engines_parallel(symbol, final_payload, candles_dict)
                
            final_payload['analysis'] = {
                'trend_direction': trend_data['direction'],
                'trend_strength': trend_data['strength'],
                'trend_type': trend_data['type'],
                'volatility_regime': volatility_data['regime']
            }
            final_payload['engines'] = {
                'trend': trend_data,
                'strength': strength_data,
                'volatility': volatility_data,
                'structure': structure_data,
                'mtf': mtf_data
            }
        except Exception as e:
            raise

        # ── 5. Market State Classifier ──────────────────────────────────
        state_data = None
        try:
            if not self.classifier:
                raise ValueError("FAIL-FAST: MarketStateClassifier not initialized")
                
            # Zero Tolerance validation before classification
            if not isinstance(final_payload, dict):
                raise ValueError("FAIL-FAST: final_payload must be a dictionary")
            if not trend_data or not strength_data or not volatility_data or not structure_data or not mtf_data:
                raise ValueError("FAIL-FAST: Missing engine data for classification")
            if not candles_dict:
                raise ValueError("FAIL-FAST: Missing candles_dict for classification")
                
            state_data = self.classifier.analyze(
                payload=final_payload,
                symbol=symbol,
                trend_data=trend_data,
                strength_data=strength_data,
                volatility_data=volatility_data,
                structure_data=structure_data,
                mtf_data=mtf_data,
                candles_dict=candles_dict
            )
            
            # Validate state_data structure
            if not isinstance(state_data, dict):
                raise ValueError("FAIL-FAST: MarketStateClassifier returned non-dict")
            if 'state' not in state_data or state_data['state'] is None:
                raise ValueError("FAIL-FAST: MarketStateClassifier missing required field: state")
                
            final_payload['market_state'] = state_data['state']
            final_payload['market_state_full'] = state_data
        except Exception as e:
            raise

        # ── 5.05 10 Supplementary Engines Execution ─────────────────────
        try:
            supp_engines = self._run_supplementary_engines(
                symbol=symbol,
                payload=final_payload,
                candles_dict=candles_dict,
                trend_data=trend_data,
                strength_data=strength_data,
                volatility_data=volatility_data,
                structure_data=structure_data,
                mtf_data=mtf_data,
                state_data=state_data
            )
            final_payload['supplementary_engines'] = supp_engines
        except Exception as e:
            logger.exception(f"Error running supplementary engines for {symbol}: {e}")
            traceback.print_exc()
            raise

        # ── 5.1 Append Group B specific fields ──────────────────────────
        try:
            m5_data = final_payload['m5']
            atr = m5_data['atr14']
            close_price = final_payload['m5']['close']
            try:
                import math
                if isinstance(close_price, (int, float)) and close_price > 0 and not math.isnan(close_price):
                    expected_vol = round((atr / close_price) * 100, 3)
                else:
                    raise ValueError("Failed to calculate expected_vol: close_price invalid")
            except (ZeroDivisionError, ValueError, TypeError) as e:
                raise ValueError("Failed to calculate expected_vol") from e

            vol_ratio = 1.0 if is_otc else m5_data.get('volume_ratio', 1.0)
            if is_otc:
                effective_news_impact = 'NONE_OTC'
            else:
                effective_news_impact = news_impact if news_impact is not None else check_news_impact(symbol)

            if is_otc:
                # OTC pairs do not have reliable news and volume from the regular market calendar.
                # We preserve the structural fields but mark them explicitly and use neutral values so
                # downstream AI, strategy, and classifier logic can treat OTC as "not applicable" without
                # introducing a zero-bias or misleading numeric signal.
                if 'm5' in final_payload and isinstance(final_payload['m5'], dict):
                    final_payload['m5']['volume'] = 1.0
                    final_payload['m5']['volume_ratio'] = 1.0
                    final_payload['m5']['volume_trend'] = 'NO_VOLUME_DATA'
                if 'm1' in final_payload and isinstance(final_payload['m1'], dict):
                    final_payload['m1']['volume'] = 1.0
                    final_payload['m1']['volume_ratio'] = 1.0

            final_payload['market_context'] = {
                'state': final_payload['market_state'],
                'description': state_data['description'] if state_data else 'NONE',
                'breakout_prob': state_data.get('breakout_prob', 0) if state_data else 0,
                'reversal_prob': state_data.get('reversal_prob', 0) if state_data else 0,
                'volatility_regime': final_payload['analysis']['volatility_regime'],
                'news_impact': effective_news_impact,
                'expected_volatility_%': expected_vol,
                'recent_ai_memory': list(self.ai_memory)
            }

            final_payload['decision_layer'] = {
                'tradeable': state_data['tradeable'] if state_data else True,
                'stability_score': state_data['metrics']['alignment_score'] if state_data else 50,
                'quality_score': state_data['quality_score'] if state_data else 50,
                'risk_level': state_data['risk_level'] if state_data else 'MEDIUM',
                'confidence_score': "รอการวิเคราะห์จาก AI",
                'suggested_expiry_minutes': "รอการวิเคราะห์จาก AI",
                'suggested_action': "รอการวิเคราะห์จาก AI"
            }

            final_payload = self._enrich_believe_analysis(final_payload)
        except Exception as e:
            raise

        # ── 5.5 Deduplicate Payload ──────────────────────────────────────
        try:
            final_payload = self._deduplicate_payload(final_payload)
        except Exception as e:
            raise

        # ── 6. Format Payload ───────────────────────────────────────────
        try:
            formatted_payload = self._format_payload(final_payload)

            if self.enable_txt_export:
                try:
                    txt_filepath = self._save_txt_payload(symbol, formatted_payload)
                    formatted_payload['txt_filepath'] = txt_filepath
                except Exception as e:
                    logger.exception(f"Orchestrator failed to save txt payload for {symbol}: {e}")
                    raise
                
            self.last_payload = formatted_payload
            self.latest_payloads[symbol] = formatted_payload
            store.clear_symbol(symbol)  # Clean up memory leak
            return formatted_payload
        except Exception as e:
            raise

    def export_txt_payload(self, symbol: Optional[str] = None) -> Optional[str]:
        """
        On-demand debug switch to export formatted payload to .txt file.
        Use this when diagnosing issues to inspect snapshot on disk.
        """
        if symbol and symbol in self.latest_payloads:
            return self._save_txt_payload(symbol, self.latest_payloads[symbol])
        elif self.last_payload is not None:
            sym = symbol or self.last_payload.get('meta', {}).get('symbol', 'UNKNOWN')
            return self._save_txt_payload(sym, self.last_payload)
        return None

    def _format_payload(self, p: dict) -> dict:
        """
        Build a structured payload from the data already produced by the indicator store,
        advanced tools, and market classification engines.
        No fallbacks — if a required field is missing, raise immediately.
        This new version reorganizes the output for better readability in the TXT log,
        grouping core analytical fields at the top.
        """
        is_otc = 'OTC' in str(p.get('symbol', '')).upper()

        def _req(d: dict, k1: str, k2: str = None, k3: str = None):
            try:
                val = d[k1]
                if k2 is not None:
                    val = val[k2]
                    if k3 is not None:
                        val = val[k3]
            except (KeyError, TypeError):
                path = f"{k1}" + (f" -> {k2}" if k2 else "") + (f" -> {k3}" if k3 else "")
                raise ValueError(f"Required field missing: {path}")
            if val is None:
                path = f"{k1}" + (f" -> {k2}" if k2 else "") + (f" -> {k3}" if k3 else "")
                raise ValueError(f"Required field is None: {path}")
            return val

        m5   = _req(p, 'm5')
        m1   = _req(p, 'm1')
        s30  = _req(p, 's30')
        meta = _req(p, 'meta')
        pa   = _req(p, 'price_action')
        eng  = _req(p, 'engines')
        dl   = _req(p, 'decision_layer')
        mc   = _req(p, 'market_context')
        adv_sig = _req(p, 'advanced_signals')
        
        # ─── CORE ANALYSIS (83 Fields) ───────────────────────────────────
        core_analysis = {
            # --- Market Context & State (5 fields) ---
            'state': _req(mc, 'state'),
            'description': _req(mc, 'description'),
            'volatility_regime': _req(p, 'analysis', 'volatility_regime'),
            'news_impact': 'NONE_OTC' if is_otc else _req(mc, 'news_impact'),
            'expected_volatility_%': _req(mc, 'expected_volatility_%'),
            
            # --- M5 Indicators (18 fields) ---
            'm5_bias': _req(m5, 'bias'),
            'm5_ema5': _req(m5, 'ema5'),
            'm5_ema10': _req(m5, 'ema10'),
            'm5_ema20': _req(m5, 'ema20'),
            'm5_ema50': _req(m5, 'ema50'),
            'm5_bb_upper': _req(m5, 'bb_upper'),
            'm5_bb_lower': _req(m5, 'bb_lower'),
            'm5_bb_width': _req(m5, 'bb_width'),
            'm5_rsi': _req(m5, 'rsi14'),
            'm5_stoch_k': _req(m5, 'stoch_k'),
            'm5_stoch_d': _req(m5, 'stoch_d'),
            'm5_macd': _req(m5, 'macd'),
            'm5_macd_signal': _req(m5, 'macd_signal'),
            'm5_adx': _req(m5, 'adx'),
            'm5_atr': _req(m5, 'atr14'),
            'm5_support': _req(m5, 'support'),
            'm5_resistance': _req(m5, 'resistance'),
            'm5_pivot': _req(m5, 'pivot'),
            
            # --- M1 Indicators (8 fields) ---
            'm1_bias': _req(m1, 'bias'),
            'm1_last_candle': 'BULLISH' if _req(p['ohlcv'], 'm1_close') > _req(p['ohlcv'], 'm1_open') else 'BEARISH',
            'm1_ema5': _req(m1, 'ema5'),
            'm1_ema20': _req(m1, 'ema20'),
            'm1_rsi': _req(m1, 'rsi14'),
            'm1_stoch_k': _req(m1, 'stoch_k'),
            'm1_stoch_d': _req(m1, 'stoch_d'),
            'm1_macd': _req(m1, 'macd'),
            'm1_macd_signal': _req(m1, 'macd_signal'),
            
            # --- M15 Compatibility Field (not calculated in strategies mode) ---
            # Keep the legacy payload shape without fabricating M15 from M5.
            'm15_bias': 'NOT_CALCULATED',
            
            # --- Advanced Tools (Price Action & Volume) (16 fields) ---
            'pa_pattern': _req(pa, 'pattern'),
            'pa_last_candle_bias': _req(pa, 'last_candle_bias'),
            'pa_body_strength': _req(pa, 'body_strength'),
            'pa_wick_dominance': _req(pa, 'wick_dominance'),
            'pa_momentum_bias': _req(pa, 'momentum_bias'),
            'pa_move_quality': _req(pa, 'move_quality'),
            'pa_trap_alert': _req(pa, 'trap_alert'),
            'pa_sr_interaction': _req(pa, 'sr_interaction'),
            'pa_divergence_alert': _req(pa, 'divergence_alert'),
            'pa_divergence_strength': _req(pa, 'divergence_strength'),
            'pa_market_behavior': _req(pa, 'market_behavior'),
            'pa_hesitation_score': _req(pa, 'hesitation_score'),
            'pa_path_efficiency': _req(pa, 'path_efficiency'),
            'vol_tick_volume': 1.0 if is_otc else float(_req(p['ohlcv'], 'm5_volume')),
            'vol_momentum': 'NO_VOLUME_DATA' if is_otc else _req(pa, 'volume_momentum'),
            'vol_vs_average': 1.0 if is_otc else _req(m5, 'volume_ratio'),

            # --- Tier-1 Engine Analysis (19 fields) ---
            'eng_trend_direction': _req(eng, 'trend', 'direction'),
            'eng_trend_strength': _req(eng, 'trend', 'strength'),
            'eng_trend_type': _req(eng, 'trend', 'type'),
            'eng_strength_momentum_bias': _req(eng, 'strength', 'momentum_level'),
            'eng_strength_momentum_strength': _req(eng, 'strength', 'strength_score'),
            'eng_strength_exhaustion_risk': _req(eng, 'strength', 'exhaustion_risk'),
            'eng_volatility_regime': _req(eng, 'volatility', 'regime'),
            'eng_volatility_compression_detected': _req(eng, 'volatility', 'spike_detected'),
            'eng_volatility_compression_quality': _req(eng, 'volatility', 'compression_quality'),
            'eng_volatility_score': _req(eng, 'volatility', 'volatility_score'),
            'eng_structure_type': _req(eng, 'structure', 'structure_type'),
            'eng_structure_bos_detected': _req(eng, 'structure', 'bos_detected'),
            'eng_mtf_alignment_score': _req(eng, 'mtf', 'alignment_score'),
            'eng_mtf_htf_direction': _req(eng, 'mtf', 'htf_direction'),
            'eng_indicator_conflict_score': _req(adv_sig, 'conflict_score'),
            'eng_trend_continuation_%': _req(adv_sig, 'continuation_probability'),
            'eng_regime_transition_risk': _req(adv_sig, 'transition_risk'),
            'eng_momentum_persistence_score': _req(adv_sig, 'persistence_score'),

            # --- Decision Layer (7 fields) ---
            'dl_tradeable': _req(dl, 'tradeable'),
            'dl_stability_score': _req(dl, 'stability_score'),
            'dl_quality_score': _req(dl, 'quality_score'),
            'dl_risk_level': _req(dl, 'risk_level'),
            'dl_confidence_score': _req(dl, 'confidence_score'),
            'dl_suggested_expiry_minutes': _req(dl, 'suggested_expiry_minutes'),
            'dl_suggested_action': _req(dl, 'suggested_action'),
        }

        # ─── SUPPLEMENTARY DATA (Remaining Fields) ───────────────────────
        def _derive_session():
            now_utc = datetime.now(timezone.utc)
            h = now_utc.hour
            if 0 <= h < 7:   return "SYDNEY/TOKYO"
            elif 7 <= h < 12: return "LONDON_OPEN"
            elif 12 <= h < 16: return "NY/LONDON_OVERLAP"
            elif 16 <= h < 21: return "NY_AFTERNOON"
            else:             return "SYDNEY_OPEN"

        supplementary_data = {
            'meta': {
                'timestamp': p.get('timestamp', datetime.now().isoformat()),
                'symbol': _req(p, 'symbol'),
                'session': meta.get('session') or _derive_session(),
                'm1_open': _req(p['ohlcv'], 'm1_open'),
                'm1_age': _req(p['ohlcv'], 'm1_age'),
                'm1_quality': _req(p['ohlcv'], 'm1_quality'),
                'm5_open': _req(p['ohlcv'], 'm5_open'),
                'm5_age': _req(p['ohlcv'], 'm5_age'),
                'm5_quality': _req(p['ohlcv'], 'm5_quality'),
                'expiry_minutes': 5,
                'holding_period': '5m',
                'entry_timeframe': 'S30',
                'trigger_timeframe': 'M1',
                'context_timeframe': 'M5',
            },
            'ohlcv': {
                's30': { 'open': _req(s30, 'open'), 'high': _req(s30, 'high'), 'low': _req(s30, 'low'), 'close': _req(s30, 'close'), 'volume': _req(s30, 'volume') },
                'm1': { 'open': _req(m1, 'open'), 'high': _req(m1, 'high'), 'low': _req(m1, 'low'), 'close': _req(m1, 'close'), 'volume': 'NONE_OTC' if is_otc else _req(p['ohlcv'], 'm1_volume') },
                'm5': { 'open': _req(m5, 'open'), 'high': _req(m5, 'high'), 'low': _req(m5, 'low'), 'close': _req(m5, 'close'), 'volume': 'NONE_OTC' if is_otc else _req(p['ohlcv'], 'm5_volume') },
            },
            's30_indicators': {k: v for k, v in s30.items() if k not in {'open', 'high', 'low', 'close', 'volume'}},
            'full_engine_output': _req(p, 'engines'),
            'full_market_state': _req(p, 'market_state_full'),
            'supplementary_engines': p.get('supplementary_engines', {}),
            'recent_ai_memory': list(self.ai_memory),
            'believe': p.get('believe'),
            'ap_confirmation': p.get('ap_confirmation'),
            'ns_confirmation': p.get('ns_confirmation'),
            'extreme_believe': p.get('extreme_believe'),
            'belief_summary': p.get('belief_summary'),
        }

        # --- Final Assembly ---
        return {
            'core_analysis': core_analysis,
            'supplementary_data': supplementary_data,
        }

    def _run_engines_parallel(self, symbol: str, payload: dict, candles_dict: dict):
        tasks: Dict[str, tuple] = {
            'trend':      (self.trend_engine.analyze,      (payload,),      {'candles_dict': candles_dict}),
            'strength':   (self.strength_engine.analyze,   (payload,),      {'candles_dict': candles_dict}),
            'volatility': (self.volatility_engine.analyze, (payload,),      {'candles_dict': candles_dict}),
            'structure':  (self.structure_engine.analyze,  (payload,),      {'candles_dict': candles_dict}),
            'mtf':        (self.mtf_engine.analyze,        (payload,),      {'candles_dict': candles_dict})
        }

        results: Dict[str, Any] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_label = {
                executor.submit(fn, *args, **kwargs): label
                for label, (fn, args, kwargs) in tasks.items()
            }
            for future in concurrent.futures.as_completed(future_to_label):
                label = future_to_label[future]
                try:
                    results[label] = future.result()
                except Exception as exc:
                    raise

        # Zero Tolerance: Validate all engine results
        if len(results) < 5:
            missing = set(['trend', 'strength', 'volatility', 'structure', 'mtf']) - set(results.keys())
            raise ValueError(f"FAIL-FAST: {len(missing)} engines failed to produce results: {missing}")
            
        # Validate each engine result structure
        required_engine_fields = {
            'trend': ['direction', 'strength', 'slope', 'momentum', 'type', 'confidence'],
            'strength': ['adx', 'di_plus', 'di_minus', 'rsi', 'momentum_level', 'strength_score', 'exhaustion_risk'],
            'volatility': ['regime', 'spike_detected', 'compression_quality', 'volatility_score'],
            'structure': ['structure_type', 'bos_detected', 'support_levels', 'resistance_levels'],
            'mtf': ['alignment_score', 'htf_direction']
        }
        
        for engine_name, result in results.items():
            if result is None:
                raise ValueError(f"FAIL-FAST: {engine_name} returned None")
            if not isinstance(result, dict):
                raise ValueError(f"FAIL-FAST: {engine_name} returned non-dict: {type(result)}")
                
            required_fields = required_engine_fields[engine_name]
            for field in required_fields:
                if field not in result or result[field] is None:
                    raise ValueError(f"FAIL-FAST: {engine_name} missing required field: {field}")
                    
        return (
            results['trend'],
            results['strength'],
            results['volatility'],
            results['structure'],
            results['mtf'],
        )

    def _run_supplementary_engines(
        self,
        symbol: str,
        payload: Dict[str, Any],
        candles_dict: Dict[str, pd.DataFrame],
        trend_data: Dict[str, Any],
        strength_data: Dict[str, Any],
        volatility_data: Dict[str, Any],
        structure_data: Dict[str, Any],
        mtf_data: Dict[str, Any],
        state_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Executes 10 supplementary engines in strict compliance with AGENTS.md.
        No silent failures, strict type checking, and defensive validation.
        """
        if not isinstance(candles_dict, dict) or 'M5' not in candles_dict:
            raise ValueError("[SupplementaryEngines] FAIL-FAST: candles_dict missing 'M5'")

        df_m5 = candles_dict['M5']
        if not isinstance(df_m5, pd.DataFrame) or df_m5.empty:
            raise ValueError("[SupplementaryEngines] FAIL-FAST: df_m5 is not a valid non-empty DataFrame")

        # 1. Execute 4 independent DataFrame-based engines in parallel
        supp_tasks = {
            'ms': (self.market_structure_engine.analyze, (df_m5,)),
            'mp': (self.market_pressure_analyzer.analyze, (df_m5,)),
            'liq': (self.liquidity_engine.analyze, (df_m5,)),
            'noise': (self.noise_detector.analyze, (df_m5,))
        }
        supp_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_key = {
                executor.submit(fn, *args): key
                for key, (fn, args) in supp_tasks.items()
            }
            for future in concurrent.futures.as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    res = future.result()
                    if not isinstance(res, dict):
                        raise ValueError(f"[{key}] returned non-dict result")
                    supp_results[key] = res
                except Exception as e:
                    logger.exception(f"[{key}] Error during analysis: {e}")
                    traceback.print_exc()
                    raise

        ms_res = supp_results['ms']
        mp_res = supp_results['mp']
        liq_res = supp_results['liq']
        noise_res = supp_results['noise']

        try:
            if state_data and 'metrics' in state_data:
                m = state_data['metrics']
                overall = m.get('regime_quality_score', 50)
                rq_res = {
                    'consistency_score': m.get('consistency_score', 50),
                    'cleanliness_score': m.get('cleanliness_score', 50),
                    'directionality_score': m.get('directionality_score', 50),
                    'overall_quality': overall,
                    'is_tradeable_regime': overall >= 60,
                    'confidence': min(100, overall + 10)
                }
            else:
                rq_res = {}
        except Exception as e:
            logger.exception(f"[RegimeQualityScorer] Error mapping from state_data: {e}")
            traceback.print_exc()
            raise

        # 2. Build MarketContext for synthesis engines
        try:
            ctx = SimpleNamespace(
                symbol=symbol,
                timeframe="M5",
                continuation=payload.get('continuation') or {'continuation_probability': 50, 'bias': 'NONE'},
                divergence=payload.get('divergence') or {'divergence_detected': False, 'divergence_type': 'NONE', 'divergence_strength': 0},
                candle_patterns=payload.get('candle_pattern') or {'bias': 'NONE', 'pattern_strength': 0},
                conflict=payload.get('conflict') or {'ema_direction': 'NONE', 'conflict_score': 0},
                efficiency=payload.get('efficiency') or {'overall_efficiency': 50},
                traps=payload.get('trap_detector') or {'trap_detected': False, 'trap_type': 'NONE'},
                transition=payload.get('transition') or {'in_transition': False, 'transition_type': 'NONE'},
                persistence=payload.get('persistence') or {'persistence_score': 50, 'is_persistent': False},
                signal_quality={'quality_score': 50, 'grade': 'C', 'confirmation_score': 50},
                confidence_framework={'confidence_tier': 'MEDIUM', 'final_confidence': 50}
            )
            ctx.trend = trend_data
            ctx.strength = strength_data
            ctx.volatility = volatility_data
            ctx.structure = structure_data
            ctx.market_structure = ms_res
            ctx.mtf = mtf_data
            ctx.market_state = state_data.get('state', 'UNKNOWN') if isinstance(state_data, dict) else str(state_data)
            ctx.regime_quality = rq_res
            ctx.orderflow = mp_res
            ctx.liquidity = liq_res
            ctx.noise = noise_res
            ctx.price_action = payload.get('price_action', {})
        except Exception as e:
            logger.exception(f"[MarketContext] Failed to build context for synthesis: {e}")
            traceback.print_exc()
            raise

        # 3. Execute 3 context-based synthesis engines
        try:
            syn_res = self.context_synthesizer.analyze(context=ctx)
            if not isinstance(syn_res, dict):
                raise ValueError("[ContextSynthesizer] returned non-dict result")
            ctx.synthesized_context = syn_res
        except Exception as e:
            logger.exception(f"[ContextSynthesizer] Error during analysis: {e}")
            traceback.print_exc()
            raise

        try:
            prob_res = self.probability_estimator.analyze(context=ctx)
            if not isinstance(prob_res, dict):
                raise ValueError("[ProbabilityEstimator] returned non-dict result")
            ctx.move_probability = prob_res
        except Exception as e:
            logger.exception(f"[ProbabilityEstimator] Error during analysis: {e}")
            traceback.print_exc()
            raise

        try:
            exp_res = self.explainability_engine.analyze(context=ctx)
            if not isinstance(exp_res, dict):
                raise ValueError("[ExplainabilityEngine] returned non-dict result")
            ctx.explainability = exp_res
        except Exception as e:
            logger.exception(f"[ExplainabilityEngine] Error during analysis: {e}")
            traceback.print_exc()
            raise

        # 4. Check SignalThrottle
        try:
            action = payload.get('decision_layer', {}).get('suggested_action', 'WAIT')
            allowed, reason = self.signal_throttle.allow(symbol, action)
            throttle_res = {
                'allowed': bool(allowed),
                'reason': str(reason),
                'status': self.signal_throttle.get_status()
            }
        except Exception as e:
            logger.exception(f"[SignalThrottle] Error during throttle check: {e}")
            traceback.print_exc()
            raise

        return {
            'explainability_engine': exp_res,
            'liquidity_engine': liq_res,
            'noise_detector': noise_res,
            'probability_estimator': prob_res,
            'signal_throttle': throttle_res,
            'context_synthesizer': syn_res,
            'market_structure_engine': ms_res,
            'market_pressure_analyzer': mp_res,
            'regime_quality_scorer': rq_res,
        }

    def _log_red(self, msg: str):
        logger.error(f"[ORCHESTRATOR ERROR] {msg}")

    @staticmethod
    def _calculate_believe_indicators(df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate the S30-only indicator snapshot required by Believe."""
        if df is None or len(df) < 20:
            raise ValueError("FAIL-FAST: S30 requires at least 20 candles for Believe indicators")
        close = pd.to_numeric(df["close"], errors="coerce")
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        ema5 = close.ewm(span=5, adjust=False).mean()
        ema10 = close.ewm(span=10, adjust=False).mean()
        ema20 = close.ewm(span=20, adjust=False).mean()
        middle = close.rolling(20).mean()
        std = close.rolling(20).std(ddof=0)
        upper = middle + 2 * std
        lower = middle - 2 * std
        delta = close.diff()
        gains = delta.clip(lower=0).rolling(14).mean()
        losses = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gains / losses.replace(0, np.nan)
        rsi = (100 - (100 / (1 + rs))).fillna(50)
        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        stoch_k = ((close - low14) / (high14 - low14).replace(0, np.nan) * 100).fillna(50)
        stoch_d = stoch_k.rolling(3).mean().fillna(stoch_k)
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        last = lambda series, default=0.0: float(series.iloc[-1]) if pd.notna(series.iloc[-1]) else default
        prev_fast, prev_slow = ema5.iloc[-2], ema10.iloc[-2]
        curr_fast, curr_slow = ema5.iloc[-1], ema10.iloc[-1]
        golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
        death_cross = prev_fast >= prev_slow and curr_fast < curr_slow
        return {
            "bias": "BULLISH" if last(close) >= last(ema20) else "BEARISH",
            "ema5": last(ema5),
            "ema10": last(ema10),
            "ema20": last(ema20),
            "bb_upper": last(upper),
            "bb_middle": last(middle),
            "bb_lower": last(lower),
            "bb_percent_b": round((last(close) - last(lower)) / (last(upper) - last(lower)), 6)
            if last(upper) != last(lower) else 0.5,
            "bb_width": last(upper) - last(lower),
            "rsi": round(last(rsi), 2),
            "stoch_k": round(last(stoch_k), 2),
            "stoch_d": round(last(stoch_d), 2),
            "macd": last(macd),
            "macd_signal": last(macd_signal),
            "macd_histogram": last(macd - macd_signal),
            "stoch_cross": (
                "GOLDEN_CROSS" if last(stoch_k) > last(stoch_d)
                else "DEATH_CROSS" if last(stoch_k) < last(stoch_d) else "NONE"
            ),
            "stoch_tangled": bool(abs(last(stoch_k) - last(stoch_d)) < 2),
            "ma_cross": "GOLDEN_CROSS" if golden_cross else "DEATH_CROSS" if death_cross else "NONE",
            "ma_cross_confirmed": bool(golden_cross or death_cross),
        }

    @staticmethod
    def _build_grid_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Expose nearest levels for S30/M1/M5 without inventing M15 data."""
        s30 = payload.get("s30", {}) or {}
        m1 = payload.get("m1", {}) or {}
        m5 = payload.get("m5", {}) or {}
        levels = {
            "S30": (s30.get("high"), s30.get("low"), s30.get("close")),
            "M1": (m1.get("high"), m1.get("low"), m1.get("close")),
            "M5": (m5.get("resistance"), m5.get("support"), m5.get("close")),
        }
        per_tf = {}
        blocked_timeframes = []
        atr = float(m5.get("atr") or 0.0)
        tolerance = max(atr * 0.50, abs(float(m5.get("close") or 0.0)) * 0.0002)
        for tf, (above, below, close) in levels.items():
            try:
                close_f = float(close)
                above_f = float(above)
                below_f = float(below)
            except (TypeError, ValueError):
                continue
            per_tf[tf] = {
                "nearest_grid_above": above_f,
                "nearest_grid_below": below_f,
                "dist_to_upper": abs(above_f - close_f),
                "dist_to_lower": abs(close_f - below_f),
                "is_blocking": False,
            }
            if tf == "M5":
                near_support = abs(close_f - below_f) <= tolerance
                near_resistance = abs(above_f - close_f) <= tolerance
                per_tf[tf]["is_blocking"] = near_support or near_resistance
                if per_tf[tf]["is_blocking"]:
                    blocked_timeframes.append(tf)
        return {
            "blocked": bool(blocked_timeframes),
            "blocked_timeframes": blocked_timeframes,
            "tolerance": tolerance,
            "retest_valid": False,
            "timeframes": per_tf,
        }

    def _enrich_believe_analysis(self, payload: dict) -> dict:
        """Build Believe from S30 entry, M1 trigger, and M5 context."""
        s30 = payload.get("s30", {}) or {}
        m5 = payload.get("m5", {}) or {}
        m1 = payload.get("m1", {}) or {}
        price_action = payload.get("price_action", {}) or {}
        market_state = payload.get("market_state_full", {}) or {}
        ohlcv = payload.get("ohlcv", {}) or {}

        def _num(value, default=0.0):
            try:
                if value is None or value == "":
                    return float(default)
                return float(value)
            except (TypeError, ValueError):
                return float(default)

        close = _num(s30.get("close", 0.0))

        # Believe is evaluated in the configured roles:
        # S30 entry, M1 trigger, M5 context.
        upper = _num(s30.get("bb_upper"), 0.0)
        lower = _num(s30.get("bb_lower"), 0.0)
        bb_pct_b = 0.5 if upper == lower else (close - lower) / (upper - lower)
        if not (0 <= bb_pct_b <= 1):
            bb_pct_b = 0.5

        stoch_k = _num(s30.get("stoch_k", 50.0), 50.0)
        stoch_d = _num(s30.get("stoch_d", 50.0), 50.0)
        rsi = _num(s30.get("rsi"), 50.0)
        macd = _num(s30.get("macd"), 0.0)
        macd_signal = _num(s30.get("macd_signal"), 0.0)
        ema_fast = _num(s30.get("ema5"), 0.0)
        ema_slow = _num(s30.get("ema10"), 0.0)
        ema20 = _num(s30.get("ema20"), 0.0)
        trigger_direction = str(m1.get("bias") or "").upper()
        context_direction = str(m5.get("bias") or "").upper()

        ma_fast_above_slow = ema_fast >= ema_slow
        ma_fast_above_20 = ema_fast >= ema20
        ma_cross_direction = "GOLDEN_CROSS" if ma_fast_above_slow else "DEATH_CROSS"
        if ema_fast == ema_slow:
            ma_cross_direction = "FLAT"

        stochastic_extreme = "MID"
        if stoch_k <= 10:
            stochastic_extreme = "OVERSOLD_10"
        elif stoch_k >= 90:
            stochastic_extreme = "OVERBOUGHT_90"

        bullish_structure = trigger_direction in ("BULLISH", "UP", "UPTREND")
        bearish_structure = trigger_direction in ("BEARISH", "DOWN", "DOWNTREND")

        hook_confirmed = (stoch_k >= stoch_d) and ((stoch_k >= 50 and bullish_structure) or (stoch_k <= 50 and bearish_structure))
        kd_crossed = stoch_k >= stoch_d
        crossed_50 = (stoch_k >= 50 and stoch_d < 50) or (stoch_k <= 50 and stoch_d > 50)
        is_surfing_extreme = (stoch_k <= 10 or stoch_k >= 90) and (stoch_d <= 20 or stoch_d >= 80)

        divergence_detected = bool(
            price_action.get("divergence_alert") in ("BULLISH", "BEARISH")
            or bool(market_state.get("divergence_detected"))
        )
        divergence_type = str(price_action.get("divergence_alert") or market_state.get("divergence_type") or "NONE").upper()
        if divergence_type == "NONE" and bullish_structure:
            divergence_type = "BULLISH"
        if divergence_type == "NONE" and bearish_structure:
            divergence_type = "BEARISH"

        ma_cross = str(s30.get("ma_cross", "NONE")).upper()
        ma_confirmed = bool(s30.get("ma_cross_confirmed", False))
        bb_confirmed = bb_pct_b <= 0.15 if bullish_structure else bb_pct_b >= 0.85
        stochastic_confirmed = (
            stoch_k <= 10 if bullish_structure else stoch_k >= 90
        )
        grid = self._build_grid_payload(payload)
        risk_filter_ok = (
            not grid["blocked"]
            and not bool(price_action.get("trap_alert") in ("TRAP", "GRID_BLOCK"))
            and not bool(price_action.get("pattern") in ("DOJI", "GRAY_DOJI"))
        )

        bullish_score = 0.0
        bearish_score = 0.0
        if ma_fast_above_slow and bullish_structure:
            bullish_score += 0.30
        if not ma_fast_above_slow and bearish_structure:
            bearish_score += 0.30
        if stochastic_extreme == "OVERSOLD_10" and bullish_structure:
            bullish_score += 0.25
        if stochastic_extreme == "OVERBOUGHT_90" and bearish_structure:
            bearish_score += 0.25
        if bb_pct_b <= 0.20 and bullish_structure:
            bullish_score += 0.15
        if bb_pct_b >= 0.80 and bearish_structure:
            bearish_score += 0.15
        if rsi < 30 and bullish_structure:
            bullish_score += 0.15
        if rsi > 70 and bearish_structure:
            bearish_score += 0.15
        if macd > macd_signal and bullish_structure:
            bullish_score += 0.10
        if macd < macd_signal and bearish_structure:
            bearish_score += 0.10
        if divergence_detected and divergence_type in ("BULLISH", "BEARISH"):
            if bullish_structure and divergence_type == "BULLISH":
                bullish_score += 0.15
            if bearish_structure and divergence_type == "BEARISH":
                bearish_score += 0.15
        if risk_filter_ok:
            bullish_score += 0.05
            bearish_score += 0.05

        bullish_signal = bullish_score >= 0.60 and bullish_structure
        bearish_signal = bearish_score >= 0.60 and bearish_structure
        if bullish_signal and bearish_signal:
            bullish_signal = bullish_score > bearish_score
            bearish_signal = bearish_score > bullish_score

        signal_direction = "BUY" if bullish_signal else "SELL" if bearish_signal else "WAIT"
        extreme_confirmed = max(bullish_score, bearish_score) >= 0.75 and (bullish_signal or bearish_signal)

        believe_payload = {
            "symbol": payload.get("symbol", "UNKNOWN"),
            "timeframe": "S30",
            "entry_timeframe": "S30",
            "trigger_timeframe": "M1",
            "context_timeframe": "M5",
            "holding_period_minutes": 5,
            "analysis_window": "S30 entry + M1 trigger + M5 context",
            "entry_bias": str(s30.get("bias", "UNKNOWN")).upper(),
            "trigger_bias": trigger_direction or "UNKNOWN",
            "context_bias": context_direction or "UNKNOWN",
            "close_price": close,
            "indicators_raw": {
                "ema3": float(s30.get("ema5", 0.0) or 0.0),
                "sma6": float(s30.get("ema10", 0.0) or 0.0),
                "bb_pct_b": round(bb_pct_b, 6),
                "stoch13_k": round(stoch_k, 2),
                "stoch13_d": round(stoch_d, 2),
                "rsi14": round(rsi, 2),
                "macd": round(macd, 6),
                "macd_signal": round(macd_signal, 6),
                "fractal_high": float(m5.get("resistance") or close),
                "fractal_low": float(m5.get("support") or close),
            },
            "believe_trigger_states": {
                "ma_crossover": {
                    "cross_direction": ma_cross_direction,
                    "is_confirmed_bar_close": ma_confirmed,
                },
                "bb_state": {
                    "touched_lower_0": bb_pct_b <= 0.15,
                    "touched_upper_1": bb_pct_b >= 0.85,
                },
                "stochastic_state": {
                    "touched_extreme_10_or_90": stochastic_extreme,
                    "hook_confirmed": hook_confirmed,
                    "kd_crossed": kd_crossed,
                    "crossed_50": crossed_50,
                    "is_surfing_extreme": is_surfing_extreme,
                }
            },
            "market_structure_fractals": {
                "prev_high": float(market_state.get("prev_high") or m5.get("resistance") or close),
                "current_high": float(market_state.get("current_high") or m5.get("resistance") or close),
                "prev_low": float(market_state.get("prev_low") or m5.get("support") or close),
                "current_low": float(market_state.get("current_low") or m5.get("support") or close),
                "high_state": "HIGHER_HIGH" if bullish_structure else "LOWER_HIGH",
                "low_state": "HIGHER_LOW" if bullish_structure else "LOWER_LOW",
                "structure_shift": "BULLISH_SHIFT" if bullish_structure else "BEARISH_SHIFT" if bearish_structure else "NEUTRAL",
            },
            "extreme_combination_extras": {
                "divergence_detected": divergence_detected,
                "divergence_type": divergence_type,
                "divergence_source": "RSI_OR_STOCH" if abs(rsi - 50) > 0 else "NONE",
                "macd_side_of_zero": "BELOW_ZERO" if macd < 0 else "ABOVE_ZERO",
            },
            "risk_and_market_filters": {
                "grid_filter": grid,
                "candle_safety": {
                    "is_gray_doji": bool(price_action.get("pattern") in ("DOJI", "GRAY_DOJI")),
                    "left_opposite_momentum_heavy": bool(price_action.get("momentum_bias") in ("BEARISH", "STRONG_BEARISH")),
                    "is_extreme_volatility_spike": bool(price_action.get("move_quality") in ("EXTREME", "VOLATILITY_SPIKE")),
                }
            },
            "decision_conditions": {
                "entry_s30_bb_touch": (
                    "LOWER_0" if bb_pct_b <= 0.15
                    else "UPPER_1" if bb_pct_b >= 0.85 else "NONE"
                ),
                "trigger_m1_direction_aligned": (
                    (bullish_structure and context_direction == "BULLISH")
                    or (bearish_structure and context_direction == "BEARISH")
                ),
                "context_m5_direction_aligned": (
                    context_direction in ("BULLISH", "BEARISH")
                    and context_direction == trigger_direction
                ),
                "holding_period_minutes": 5,
            },
        }

        ap_signal = "AP_BULLISH" if bullish_signal else "AP_BEARISH" if bearish_signal else "AP_NEUTRAL"
        ap_confirmation = {
            "ap_active": bool(bullish_signal or bearish_signal),
            "signal": ap_signal,
            "source": ["BOLLINGER", "STOCH", "MACD", "MOMENTUM"],
            "confidence": "HIGH" if extreme_confirmed else "MEDIUM" if (bullish_signal or bearish_signal) else "LOW",
        }
        ns_signal = "NS_BULLISH" if bullish_signal and abs(rsi - 50) < 20 and abs(stoch_k - 50) < 20 else "NS_BEARISH" if bearish_signal and abs(rsi - 50) < 20 and abs(stoch_k - 50) < 20 else "NS_NEUTRAL"
        ns_confirmation = {
            "ns_active": bool(abs(rsi - 50) < 20 and abs(stoch_k - 50) < 20),
            "signal": ns_signal,
            "source": ["RSI", "STOCH", "STRUCTURE"],
            "confidence": "MEDIUM" if abs(rsi - 50) < 20 else "LOW",
        }

        score = max(bullish_score, bearish_score)
        setup_type = "EXTREME_BELIEVE" if extreme_confirmed else "BASE_BELIEVE"
        extreme_believe = {
            "setup_type": setup_type,
            "is_active": extreme_confirmed,
            "score": round(min(score, 1.0), 3),
            "reasons": [
                "MA crossover alignment",
                "stochastic extreme",
                "divergence confirmation",
                "structure shift",
                "risk filter passed",
            ],
        }

        payload["believe"] = believe_payload
        payload["ap_confirmation"] = ap_confirmation
        payload["ns_confirmation"] = ns_confirmation
        payload["extreme_believe"] = extreme_believe
        payload["believe_signal_type"] = setup_type
        payload["belief_summary"] = {
            "status": "active" if extreme_confirmed else "watch",
            "direction": signal_direction,
            "confidence": "HIGH" if extreme_confirmed else "MEDIUM" if (bullish_signal or bearish_signal) else "LOW",
            "score": round(score, 3),
            "signal": ap_signal,
        }
        payload["grid_filter"] = grid
        payload["timeframe_contract"] = {
            "entry": "S30",
            "trigger": "M1",
            "context": "M5",
            "holding_period_minutes": 5,
        }
        return payload

    def _deduplicate_payload(self, p: dict) -> dict:
        """Remove redundant raw values from engines and market_state to shrink payload."""
        e = p.get('engines')
        if e:
            str_eng = e.get('strength')
            if str_eng:
                for k in ('adx', 'di_plus', 'di_minus', 'rsi', 'macd', 'roc'):
                    str_eng.pop(k, None)
            vol_eng = e.get('volatility')
            if vol_eng:
                for k in ('atr', 'atr_percentile', 'bbw', 'stddev'):
                    vol_eng.pop(k, None)
            struct_eng = e.get('structure')
            if struct_eng:
                for k in ('support_levels', 'resistance_levels', 'box_duration', 'box_tightness'):
                    struct_eng.pop(k, None)
            trd_eng = e.get('trend')
            if trd_eng:
                trd_eng.pop('slope', None)

        ms_full = p.get('market_state_full')
        if ms_full and isinstance(ms_full, dict):
            ms = ms_full.get('metrics')
            if ms and isinstance(ms, dict):
                for k in ('adx', 'rsi', 'atr_percentile', 'bbw', 'trend_direction', 'trend_strength', 
                          'trend_slope', 'trend_type', 'momentum_level', 'strength_score', 
                          'volatility_regime', 'volatility_score', 'structure_type', 'bos_detected',
                          'breakout_prob', 'reversal_prob', 'alignment_score', 'htf_direction'):
                    ms.pop(k, None)

        return p

    def _flatten_dict(self, d: dict, parent_key: str = '', sep: str = '_') -> dict:
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, (list, tuple)):
                items.append((new_key, str(v)))
            elif not isinstance(v, pd.DataFrame):
                items.append((new_key, v))
        return dict(items)

    def _generate_yaml_text(self, symbol: str, fp: dict) -> str:
        """Generates a YAML string from the formatted payload and aligns colons."""
        try:
            # Clean numpy objects by routing through JSON encoder
            cleaned_fp = json.loads(json.dumps(fp, cls=NumpyEncoder))
            raw_yaml = yaml.dump(cleaned_fp, allow_unicode=True, sort_keys=False, indent=2)
            
            # Align colons for better readability
            lines = raw_yaml.split('\n')
            aligned_lines = []
            for line in lines:
                if ':' in line and not line.strip().endswith(':'):
                    k, v = line.split(':', 1)
                    # Find how many leading spaces the key has
                    leading_spaces = len(k) - len(k.lstrip())
                    # Format key padded to 25 characters (minus leading spaces to keep total width consistent)
                    padded_k = k.ljust(25)
                    aligned_lines.append(f"{padded_k}: {v.strip()}")
                else:
                    aligned_lines.append(line)
                    
            return '\n'.join(aligned_lines)
        except Exception as e:
            raise

    def _format_core_analysis_output(self, formatted_payload: dict, prompt_id: str) -> str:
        core = formatted_payload.get("core_analysis", {})
        supp = formatted_payload.get("supplementary_data", {})
        meta = supp.get("meta", {})
        ohlcv = supp.get("ohlcv", {})
        m1_ohlcv = ohlcv.get("m1", {})
        s30_ohlcv = ohlcv.get("s30", {})
        m5_ohlcv = ohlcv.get("m5", {})

        def _fmt_bool(v):
            if isinstance(v, bool):
                return "true" if v else "false"
            if str(v).lower() in ("true", "false"):
                return str(v).lower()
            return str(v)

        def _fmt_num(v):
            if v is None or v == '':
                return ''
            if isinstance(v, (int, float)):
                if isinstance(v, float) and abs(v) < 1e-4 and v != 0:
                    return f"{v:.6f}"
                return str(round(v, 6)) if isinstance(v, float) else str(v)
            return str(v)

        # Determine ai_model name from config
        cfg = getattr(self, "config", {}) or {}
        if not cfg:
            try:
                from config_setting.config_loader import load_settings
                cfg = load_settings(reload=False)
            except Exception:
                cfg = {}
        ml_cfg = cfg.get("ml_mode", {})
        ai_cfg = cfg.get("ai_mode", {})
        if str(cfg.get("active_mode", "")).lower() == "strategies_mode":
            ai_model = "STRATEGY_BELIEVE"
        elif ml_cfg.get("enabled", False):
            ai_model = str(ml_cfg.get("model", "LIGHTGBM_CHRONOS"))
        elif ai_cfg.get("enabled", False):
            ai_model = str(ai_cfg.get("provider", "GEMINI"))
        else:
            ai_model = "NONE"

        lines = []
        app = lines.append
        app(f"ID:{prompt_id}")
        app("meta:")
        app(f"  timestamp: '{meta.get('timestamp', '')}'")
        app(f"  symbol: {meta.get('symbol', '')}")
        app(f"  ai_model: {ai_model}")
        app(f"  session: {meta.get('session', '')}")
        app(f"  m1_open: {_fmt_num(meta.get('m1_open', ''))}")
        app(f"  m1_age: {meta.get('m1_age', '')}")
        app(f"  m1_quality: {meta.get('m1_quality', '')}")
        app(f"  m5_open: {_fmt_num(meta.get('m5_open', ''))}")
        app(f"  m5_age: {meta.get('m5_age', '')}")
        app(f"  m5_quality: {meta.get('m5_quality', '')}")
        app(f"  expiry_minutes: {meta.get('expiry_minutes', 5)}")
        app(f"  holding_period: {meta.get('holding_period', '5m')}")
        app(f"  entry_timeframe: {meta.get('entry_timeframe', 'S30')}")
        app(f"  trigger_timeframe: {meta.get('trigger_timeframe', 'M1')}")
        app(f"  context_timeframe: {meta.get('context_timeframe', 'M5')}")
        app("s30:")
        s30_indicators = supp.get("s30_indicators", {})
        s30_direction = str(s30_indicators.get("bias", "UNKNOWN")).upper()
        app(f"  s30_bias: {s30_direction}")
        app(f"  s30_open: {_fmt_num(s30_ohlcv.get('open', ''))}")
        app(f"  s30_high: {_fmt_num(s30_ohlcv.get('high', ''))}")
        app(f"  s30_low: {_fmt_num(s30_ohlcv.get('low', ''))}")
        app(f"  s30_close: {_fmt_num(s30_ohlcv.get('close', ''))}")
        app(f"  s30_volume: {s30_ohlcv.get('volume', '')}")
        app(f"  s30_ema5: {_fmt_num(s30_indicators.get('ema5', ''))}")
        app(f"  s30_ema10: {_fmt_num(s30_indicators.get('ema10', ''))}")
        app(f"  s30_ema20: {_fmt_num(s30_indicators.get('ema20', ''))}")
        app(f"  s30_rsi: {_fmt_num(s30_indicators.get('rsi', ''))}")
        app(f"  s30_stoch_k: {_fmt_num(s30_indicators.get('stoch_k', ''))}")
        app(f"  s30_stoch_d: {_fmt_num(s30_indicators.get('stoch_d', ''))}")
        app(f"  s30_macd: {_fmt_num(s30_indicators.get('macd', ''))}")
        app(f"  s30_macd_signal: {_fmt_num(s30_indicators.get('macd_signal', ''))}")
        app(f"  s30_macd_histogram: {_fmt_num(s30_indicators.get('macd_histogram', ''))}")
        app(f"  s30_bb_percent_b: {_fmt_num(s30_indicators.get('bb_percent_b', ''))}")
        app("market_context:")
        app(f"  mtf_state: {core.get('state', '')}")
        app(f"  mtf_description: {core.get('description', '')}")
        app(f"  m5_volatility_regime: {core.get('volatility_regime', '')}")
        app(f"  m5_news_impact: {core.get('news_impact', '')}")
        app(f"  m5_expected_volatility_%: {_fmt_num(core.get('expected_volatility_%', ''))}")
        app("timeframes:")
        app("  m1:")
        app(f"    m1_bias: {core.get('m1_bias', '')}")
        app(f"    m1_last_candle: {core.get('m1_last_candle', '')}")
        app(f"    m1_ema5: {_fmt_num(core.get('m1_ema5', ''))}")
        app(f"    m1_ema20: {_fmt_num(core.get('m1_ema20', ''))}")
        app(f"    m1_rsi: {_fmt_num(core.get('m1_rsi', ''))}")
        app(f"    m1_stoch_k: {_fmt_num(core.get('m1_stoch_k', ''))}")
        app(f"    m1_stoch_d: {_fmt_num(core.get('m1_stoch_d', ''))}")
        app(f"    m1_macd: {_fmt_num(core.get('m1_macd', ''))}")
        app(f"    m1_macd_signal: {_fmt_num(core.get('m1_macd_signal', ''))}")
        app("    ohlcv:")
        app(f"      m1_open: {_fmt_num(m1_ohlcv.get('open', ''))}")
        app(f"      m1_high: {_fmt_num(m1_ohlcv.get('high', ''))}")
        app(f"      m1_low: {_fmt_num(m1_ohlcv.get('low', ''))}")
        app(f"      m1_close: {_fmt_num(m1_ohlcv.get('close', ''))}")
        app(f"      m1_volume: {m1_ohlcv.get('volume', '')}")
        app("  m5:")
        app(f"    m5_bias: {core.get('m5_bias', '')}")
        app(f"    m5_ema5: {_fmt_num(core.get('m5_ema5', ''))}")
        app(f"    m5_ema10: {_fmt_num(core.get('m5_ema10', ''))}")
        app(f"    m5_ema20: {_fmt_num(core.get('m5_ema20', ''))}")
        app(f"    m5_ema50: {_fmt_num(core.get('m5_ema50', ''))}")
        app(f"    m5_bb_upper: {_fmt_num(core.get('m5_bb_upper', ''))}")
        app(f"    m5_bb_lower: {_fmt_num(core.get('m5_bb_lower', ''))}")
        app(f"    m5_bb_width: {_fmt_num(core.get('m5_bb_width', ''))}")
        app(f"    m5_rsi: {_fmt_num(core.get('m5_rsi', ''))}")
        app(f"    m5_stoch_k: {_fmt_num(core.get('m5_stoch_k', ''))}")
        app(f"    m5_stoch_d: {_fmt_num(core.get('m5_stoch_d', ''))}")
        app(f"    m5_macd: {_fmt_num(core.get('m5_macd', ''))}")
        app(f"    m5_macd_signal: {_fmt_num(core.get('m5_macd_signal', ''))}")
        app(f"    m5_adx: {_fmt_num(core.get('m5_adx', ''))}")
        app(f"    m5_atr: {_fmt_num(core.get('m5_atr', ''))}")
        app(f"    m5_support: {_fmt_num(core.get('m5_support', ''))}")
        app(f"    m5_resistance: {_fmt_num(core.get('m5_resistance', ''))}")
        app(f"    m5_pivot: {_fmt_num(core.get('m5_pivot', ''))}")
        app("    ohlcv:")
        app(f"      m5_open: {_fmt_num(m5_ohlcv.get('open', ''))}")
        app(f"      m5_high: {_fmt_num(m5_ohlcv.get('high', ''))}")
        app(f"      m5_low: {_fmt_num(m5_ohlcv.get('low', ''))}")
        app(f"      m5_close: {_fmt_num(m5_ohlcv.get('close', ''))}")
        app(f"      m5_volume: {m5_ohlcv.get('volume', '')}")
        app("  m15:")
        app(f"    m15_bias: {core.get('m15_bias', 'NOT_CALCULATED')}")
        app("price_action:")
        app(f"  m5_pa_pattern: {core.get('pa_pattern', '')}")
        app(f"  m5_pa_last_candle_bias: {core.get('pa_last_candle_bias', '')}")
        app(f"  m5_pa_body_strength: {core.get('pa_body_strength', '')}")
        app(f"  m5_pa_wick_dominance: {core.get('pa_wick_dominance', '')}")
        app(f"  m5_pa_momentum_bias: {core.get('pa_momentum_bias', '')}")
        app(f"  m5_pa_move_quality: {core.get('pa_move_quality', '')}")
        app(f"  m5_pa_trap_alert: {core.get('pa_trap_alert', '')}")
        app(f"  m5_pa_sr_interaction: {core.get('pa_sr_interaction', '')}")
        app(f"  m5_pa_divergence_alert: {core.get('pa_divergence_alert', 'NONE')}")
        app(f"  m5_pa_divergence_strength: {core.get('pa_divergence_strength', 0)}")
        app(f"  m5_pa_market_behavior: {core.get('pa_market_behavior', 'NEUTRAL')}")
        app(f"  m5_pa_hesitation_score: {core.get('pa_hesitation_score', 50)}")
        app(f"  m5_pa_path_efficiency: {core.get('pa_path_efficiency', 'FAIR')}")
        app("volume:")
        app(f"  m5_tick_volume: {_fmt_num(core.get('vol_tick_volume', ''))}")
        app(f"  m5_volume_momentum: {core.get('vol_momentum', '')}")
        app(f"  m5_volume_vs_average: {_fmt_num(core.get('vol_vs_average', ''))}")
        app("analysis:")
        app(f"  m5_trend_direction: {core.get('eng_trend_direction', '')}")
        app(f"  m5_trend_type: {core.get('eng_trend_type', '')}")
        app(f"  m5_trend_strength_score: {core.get('eng_trend_strength', '')}")
        app(f"  mtf_alignment_%: {core.get('eng_mtf_alignment_score', '')}")
        app(f"  m5_compression_quality_%: {core.get('eng_volatility_compression_quality', '')}")
        app(f"  m5_exhaustion_risk_%: {core.get('eng_strength_exhaustion_risk', '')}")
        app(f"  m5_bos_detected: {_fmt_bool(core.get('eng_structure_bos_detected', ''))}")
        app(f"  mtf_conflict_score: {core.get('eng_indicator_conflict_score', 0)}")
        app(f"  m5_trend_continuation_%: {core.get('eng_trend_continuation_%', 50)}")
        app(f"  m5_transition_risk: {core.get('eng_regime_transition_risk', 'LOW')}")
        app(f"  m5_persistence_score: {core.get('eng_momentum_persistence_score', 50)}")
        app("decision_layer:")
        app(f"  dl_tradeable: {_fmt_bool(core.get('dl_tradeable', ''))}")
        app(f"  dl_stability_score: {core.get('dl_stability_score', '')}")
        app(f"  dl_quality_score: {core.get('dl_quality_score', '')}")
        app(f"  dl_risk_level: {core.get('dl_risk_level', '')}")
        app(f"  ai_confidence_score: {core.get('dl_confidence_score', '')}")
        app(f"  ai_suggested_expiry_minutes: {core.get('dl_suggested_expiry_minutes', '')}")
        app(f"  ai_suggested_action: {core.get('dl_suggested_action', '')}")
        belief = supp.get("belief_summary") or {}
        extreme = supp.get("extreme_believe") or {}
        app("believe_strategy:")
        app(f"  believe_status: {belief.get('status', '')}")
        app(f"  believe_direction: {belief.get('direction', '')}")
        app(f"  believe_confidence: {belief.get('confidence', '')}")
        app(f"  believe_score: {_fmt_num(belief.get('score', ''))}")
        app(f"  extreme_believe_active: {_fmt_bool(extreme.get('is_active', False))}")
        app(f"  extreme_believe_setup: {extreme.get('setup_type', '')}")
        believe = supp.get("believe", {}) or {}
        trigger = believe.get("believe_trigger_states", {}) or {}
        bb_state = trigger.get("bb_state", {}) or {}
        sto_state = trigger.get("stochastic_state", {}) or {}
        risk = believe.get("risk_and_market_filters", {}) or {}
        grid = risk.get("grid_filter", {}) or {}
        app(f"  believe_entry_timeframe: {believe.get('entry_timeframe', 'S30')}")
        app(f"  believe_trigger_timeframe: {believe.get('trigger_timeframe', 'M1')}")
        app(f"  believe_context_timeframe: {believe.get('context_timeframe', 'M5')}")
        app(f"  believe_bb_percent_b: {_fmt_num(believe.get('indicators_raw', {}).get('bb_pct_b', ''))}")
        app(f"  believe_bb_touch: {'LOWER' if bb_state.get('touched_lower_0') else 'UPPER' if bb_state.get('touched_upper_1') else 'NONE'}")
        app(f"  believe_sto_k: {_fmt_num(believe.get('indicators_raw', {}).get('stoch13_k', ''))}")
        app(f"  believe_sto_d: {_fmt_num(believe.get('indicators_raw', {}).get('stoch13_d', ''))}")
        app(f"  believe_sto_zone: {sto_state.get('touched_extreme_10_or_90', 'MID')}")
        app(f"  believe_sto_cross: {('UP' if sto_state.get('kd_crossed') and believe.get('trigger_bias') in ('BULLISH', 'UP', 'UPTREND') else 'DOWN' if sto_state.get('kd_crossed') and believe.get('trigger_bias') in ('BEARISH', 'DOWN', 'DOWNTREND') else 'NONE')}")
        app(f"  believe_sto_hook_confirmed: {_fmt_bool(sto_state.get('hook_confirmed', False))}")
        app(f"  believe_sto_cross_50: {_fmt_bool(sto_state.get('crossed_50', False))}")
        app(f"  believe_ma_fast: {_fmt_num(believe.get('indicators_raw', {}).get('ema3', ''))}")
        app(f"  believe_ma_slow: {_fmt_num(believe.get('indicators_raw', {}).get('sma6', ''))}")
        app(f"  believe_ma_cross: {trigger.get('ma_crossover', {}).get('cross_direction', 'FLAT')}")
        app(f"  believe_ma_cross_confirmed: {_fmt_bool(trigger.get('ma_crossover', {}).get('is_confirmed_bar_close', False))}")
        app(f"  believe_risk_grid_block: {_fmt_bool(grid.get('is_blocked_by_grid', grid.get('blocked', False)))}")
        app(f"  believe_risk_gray_candle: {_fmt_bool(risk.get('candle_safety', {}).get('is_gray_doji', False))}")
        app(f"  believe_risk_sto_tangled: {_fmt_bool(s30_indicators.get('stoch_tangled', False))}")
        app(f"  believe_risk_trap_alert: {core.get('pa_trap_alert', 'NONE')}")
        app(f"  believe_risk_room_to_run_clear: {_fmt_bool(believe.get('decision_conditions', {}).get('room_to_run_clear', True))}")
        app(f"  ap_signal: {supp.get('ap_confirmation', {}).get('signal', 'AP_NEUTRAL')}")
        app(f"  ns_signal: {supp.get('ns_confirmation', {}).get('signal', 'NS_NEUTRAL')}")
        conditions = believe.get("decision_conditions", {}) or {}
        app(f"  believe_entry_s30_bb_touch: {conditions.get('entry_s30_bb_touch', 'NONE')}")
        app(f"  believe_trigger_m1_direction_aligned: {_fmt_bool(conditions.get('trigger_m1_direction_aligned', False))}")
        app(f"  believe_context_m5_direction_aligned: {_fmt_bool(conditions.get('context_m5_direction_aligned', False))}")
        app("")
        return "\n".join(lines)

    def _save_txt_payload(self, symbol: str, formatted_payload: dict) -> str:
        meta = formatted_payload.get("supplementary_data", {}).get("meta", {})
        timestamp_str = str(meta.get("timestamp", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
        ts_clean = timestamp_str.replace('-', '').replace(':', '').replace('T', '').replace('.', '')[:14]
        time_part = ts_clean[4:14]
        prompt_id = f"{symbol.replace('-', '').replace('_', '')}{time_part}"
        
        formatted_output = self._format_core_analysis_output(formatted_payload, prompt_id)
        
        filename = f"{prompt_id}.txt"
        symbol_dir = os.path.join(self.orchestrator_log_dir, symbol)
        os.makedirs(symbol_dir, exist_ok=True)
        filepath = os.path.join(symbol_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted_output)

        # Retention policy: Keep at most 30 latest prompt files per symbol
        try:
            txt_files = sorted(
                [os.path.join(symbol_dir, f) for f in os.listdir(symbol_dir) if f.endswith('.txt')],
                key=os.path.getmtime
            )
            if len(txt_files) > 30:
                for old_file in txt_files[:-30]:
                    try:
                        os.remove(old_file)
                    except OSError:
                        pass
        except Exception as e:
            logger.warning(f"[Orchestrator] Error cleaning old txt files for {symbol}: {e}")

        return filepath
