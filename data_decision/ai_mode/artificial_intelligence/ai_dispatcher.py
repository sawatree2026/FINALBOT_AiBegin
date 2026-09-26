"""
System Prompt & Prompt Formatter for Part 3 AI Decision Engine
==============================================================
Defines the authoritative System Prompt and Strict JSON Output Specification
for DeepSeek Browser Agent and Google Gemini API, with automatic prompt archiving
and decision logging to `data_base/ai_decision_output/<SYMBOL>/` retaining max 30 files per symbol.
"""

import os
import asyncio
import csv
import glob
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from data_trade.payload_sanitizer import sanitize_payload_text


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """:: คำสั่ง ::
จงทำหน้าที่เป็น Quantitative Trading AI และ Binary Options Expert 
วิเคราะห์ข้อมูลตลาดแบบ Multi-Timeframe (M1, M5, M15) ด้านล่างนี้ โดยประมวลผลทุกตัวชี้วัด
(Price Action, Technical Indicators, Volume, Market Context, Multi-Timeframe Alignment)
โดยใช้ M1 หา timing เข้า, M5 ยืนยันทิศทางระยะสั้น และ M15 กำหนดแนวโน้มหลัก
ระบบกำหนด expiry_minutes = 5 เท่านั้น เพราะ Chronos ทำนาย 5 แท่ง M1 ถัดไป
หากสัญญาณไม่ชัดเจนหรือมีความเสี่ยงสูง ให้ตอบ "action": "WAIT"

:: ข้อกำหนดการส่งผลลัพธ์ ::
- ตอบกลับในรูปแบบ JSON ตามโครงสร้างนี้เท่านั้น (ห้ามมีข้อความเกริ่นนำหรือปิดท้ายนอก JSON):
{
  "ID": "string (ต้องระบุรหัส ID เดิมที่ได้รับในบรรทัดแรก เช่น EURUSD0828082001)",
  "symbol": "string",
  "action": "CALL" | "PUT" | "WAIT",
  "expiry_minutes": 5,
  "confidence_score": 0,
  "reason_th": "เหตุผลสั้นๆ 1 ประโยค"
}"""


class SystemPrompt:
    """
    Prompt Orchestrator & Response Parser for Part 3.
    Receives 99-line payload, formats complete prompt, sends to AI transport agent,
    parses raw response, extracts & verifies original ID, saves decision to
    data_base/output_decision/ai_decision/<SYMBOL>/<ID>.txt and decisions.csv,
    and returns validated decision JSON.
    """

    MAX_RETENTION_FILES = 30
    AI_DECISION_OUTPUT_BASE_DIR = os.path.join("data_base", "output_decision", "ai_decision")
    _CHANNEL_POOL: Optional[Any] = None

    # ── BOSS ORDER: Disable JSON decision file write ──────────────────────
    # TXT recording via _save_decision_txt() and CSV recording via _save_decision_csv()
    # are active for audit/statistics.
    # To re-enable JSON legacy: set ENABLE_DECISION_JSON = True
    ENABLE_DECISION_JSON: bool = False

    @classmethod
    def prewarm_and_test_ai(cls, symbols: list) -> bool:
        """Pre-warms and tests dedicated AI channels for all symbols."""
        try:
            from .gemini_bridge import DedicatedGeminiManager
        except ImportError:
            raise RuntimeError("FAIL-FAST: Local data_trade Gemini bridge is unavailable")
        from config_setting.config_loader import load_settings
        cfg = load_settings(reload=False).get("ai_mode", {})
        model_name = cfg.get("primary_model") or cfg.get("gemini_model", "gemini-3.5-flash-lite")
        return DedicatedGeminiManager.test_connection(symbols=symbols, model_name=model_name)

    @classmethod
    def get_dedicated_agent(cls, symbol: str) -> Any:
        """Returns the dedicated 1:1 agent for a specific symbol."""
        try:
            from .gemini_bridge import DedicatedGeminiManager
        except ImportError:
            raise RuntimeError("FAIL-FAST: Local data_trade Gemini bridge is unavailable")
        return DedicatedGeminiManager.get_agent(symbol)

    @classmethod
    def get_channel_pool(cls) -> Any:
        """Legacy alias — returns DedicatedGeminiManager."""
        try:
            from .gemini_bridge import DedicatedGeminiManager
        except ImportError:
            raise RuntimeError("FAIL-FAST: Local data_trade Gemini bridge is unavailable")
        return DedicatedGeminiManager

    @classmethod
    def get_ai_agent(cls, symbol: str = "DEFAULT") -> Any:
        """Acquires the dedicated agent for the symbol."""
        return cls.get_dedicated_agent(symbol)

    @staticmethod
    def get_system_prompt() -> str:
        """Returns the master system prompt for AI analysis."""
        return SYSTEM_PROMPT.strip()

    @staticmethod
    def build_user_prompt(symbol: str, prompt_text: str) -> str:
        """
        Builds the complete user prompt to be dispatched to DeepSeek or Gemini.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("FAIL-FAST: symbol must be a non-empty string")
        if not prompt_text or not isinstance(prompt_text, str):
            raise ValueError("FAIL-FAST: prompt_text must be a non-empty string")
        prompt_text, _ = sanitize_payload_text(prompt_text, source=f"gemini:{symbol}")

        return (
            f":: ข้อมูลตลาดสำหรับวิเคราะห์ ::\n"
            f"{prompt_text.strip()}\n"
        )

    @classmethod
    def get_latest_prompt_file(cls, symbol: str, base_dir: Optional[str] = None) -> str:
        """Finds the most recent 99-line prompt file for the symbol in data_base/evaluate_output/<SYMBOL>/."""
        if base_dir is None:
            from config_setting.config_loader import load_settings
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

    @classmethod
    def read_payload_from_disk(cls, prompt_filepath: str) -> str:
        """Reads 99-line prompt text from Part 2 output file on disk."""
        if not prompt_filepath or not isinstance(prompt_filepath, str):
            raise ValueError("FAIL-FAST: prompt_filepath must be a non-empty string")
        if not os.path.isfile(prompt_filepath):
            raise FileNotFoundError(f"FAIL-FAST: Payload file not found at {prompt_filepath}")

        with open(prompt_filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            raise ValueError(f"FAIL-FAST: Payload file is empty at {prompt_filepath}")
        cleaned, _ = sanitize_payload_text(content, source=prompt_filepath)
        return cleaned

    @staticmethod
    def _extract_meta_from_payload(payload_text: Optional[str], prompt_filepath: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """Extracts original source ID and timestamp from Part 2 prompt payload text."""
        analysis_id = None
        timestamp_str = None
        if payload_text:
            for line in payload_text.splitlines():
                line_str = line.strip()
                if line_str.startswith("ID:"):
                    analysis_id = line_str.split(":", 1)[1].strip()
                elif line_str.startswith("timestamp:"):
                    timestamp_str = line_str.split(":", 1)[1].strip().strip("'\"")
                if analysis_id and timestamp_str:
                    break
        if not analysis_id and prompt_filepath:
            base_fname = os.path.splitext(os.path.basename(prompt_filepath))[0]
            if base_fname:
                analysis_id = base_fname
        return analysis_id, timestamp_str

    @classmethod
    def process_ai_decision(
        cls,
        symbol: str,
        payload_text: Optional[str] = None,
        ai_agent: Any = None,
        prompt_filepath: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main Engine Flow:
        1. Reads 99-line payload from disk (prompt_filepath or latest in data_base/evaluate_output/<SYMBOL>/) if provided, or uses payload_text.
        2. Builds complete prompt with system rules.
        3. Step 1: Receives raw output (raw_output) from AI transport agent.
        4. Step 2: Parses raw output into JSON decision (parse_json_decision) and resolves original ID.
        5. Step 3: Saves decision to data_base/ai_decision_output/<SYMBOL>/<ID>.txt and decisions.csv.
        6. Step 4: Returns structured JSON decision to executor_manager.py.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("FAIL-FAST: symbol must be a non-empty string")

        if prompt_filepath:
            payload_text = cls.read_payload_from_disk(prompt_filepath)
        elif not payload_text or not isinstance(payload_text, str):
            try:
                latest_fp = cls.get_latest_prompt_file(symbol)
                prompt_filepath = latest_fp
                payload_text = cls.read_payload_from_disk(latest_fp)
            except Exception:
                raise ValueError("FAIL-FAST: Either prompt_filepath or non-empty payload_text must be provided")

        payload_text, _ = sanitize_payload_text(
            payload_text, source=prompt_filepath or "in-memory"
        )
        analysis_id, prompt_ts = cls._extract_meta_from_payload(payload_text, prompt_filepath)
        now_utc = datetime.now(timezone.utc)
        utc_timestamp_str = prompt_ts or now_utc.strftime("%Y-%m-%d %H:%M:%S+00:00")
        if not analysis_id:
            ts_mmdd = now_utc.strftime("%m%d%H%M%S")
            clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
            analysis_id = f"{clean_sym}{ts_mmdd}"

        from config_setting.config_loader import load_settings
        cfg = load_settings(reload=False)
        stake = float(cfg.get("account", {}).get("stake_per_trade", 35.0))
        min_conf = float(cfg.get("ai_mode", {}).get("min_confidence", cfg.get("ml_mode", {}).get("min_confidence", 60.0)))

        target_agent = ai_agent
        _acquired_from_pool = False
        if target_agent is None:
            target_agent = cls.get_channel_pool().acquire()
            _acquired_from_pool = True

        if target_agent is None:
            raise RuntimeError(
                f"FAIL-FAST: Gemini transport agent unavailable for {symbol}; "
                "trading halted"
            )

        system_instruction = cls.get_system_prompt()
        user_prompt = cls.build_user_prompt(symbol, payload_text)
        full_assembled_prompt = f"{system_instruction}\n\n{user_prompt}"

        # ── Step 1-4: ทำงานกับ channel แล้ว release คืน pool เสมอ ──────────────
        try:
            # ── Step 1: รับคำตอบดิบ (raw_output) จาก AI ──────────────────────────────────
            try:
                raw_output = target_agent.send_prompt(user_prompt=user_prompt, system_instruction=system_instruction)
            except TypeError:
                raw_output = target_agent.send_prompt(full_assembled_prompt)

            # ── Step 2: บันทึกคำตอบดิบทันที As-Is (100%) ─────────────────────────────────
            cls._save_decision_txt(
                symbol=symbol,
                raw_output=raw_output,
                analysis_id=analysis_id
            )

            # ── Step 3: แกะกล่อง (Parse) ให้เป็น JSON ตามฟอร์ม (parse_json_decision) ───────
            parsed_decision = cls.parse_json_decision(
                raw_output=raw_output,
                symbol=symbol,
                ai_agent=target_agent,
                analysis_id=analysis_id,
                utc_timestamp_str=utc_timestamp_str
            )

            final_id = parsed_decision.get("ID") or analysis_id

            # Save CSV record
            cls._save_decision_csv(
                symbol=symbol,
                decision=parsed_decision,
                analysis_id=final_id,
                timestamp_str=utc_timestamp_str
            )

            # ── Step 4: คืนค่า (return) JSON decision ส่งต่อให้ executor_manager.py ────────
            return parsed_decision

        finally:
            if _acquired_from_pool:
                cls.get_channel_pool().release(target_agent)

    @classmethod
    def _save_decision_file(
        cls,
        symbol: str,
        raw_output: Any = "",
        decision: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        analysis_id: Optional[str] = None
    ) -> str:
        """Saves or updates the raw output / structured AI order decision file to data_trade/ai_output/<SYMBOL>/<FILENAME>.json."""
        # ── BOSS ORDER: Short-circuit when JSON write is disabled ─────────
        if not cls.ENABLE_DECISION_JSON:
            logger.debug(
                f"[SystemPrompt] JSON decision write DISABLED — skipping save for {symbol}"
            )
            return file_path or ""

        if isinstance(raw_output, dict) and decision is None:
            decision = raw_output
            raw_output = ""

        try:
            symbol_dir = os.path.join(cls.AI_DECISION_OUTPUT_BASE_DIR, symbol)
            os.makedirs(symbol_dir, exist_ok=True)

            now_utc = datetime.now(timezone.utc)
            timestamp_iso = now_utc.strftime("%Y-%m-%d %H:%M:%S+00:00")

            if not file_path:
                timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")
                filename = f"decision_{symbol}_{timestamp_str}.json"
                file_path = os.path.join(symbol_dir, filename)

            final_id = analysis_id or (decision.get("ID") if decision else None) or (decision.get("id") if decision else None)

            decision_record: Dict[str, Any] = {
                "timestamp": decision.get("timestamp", timestamp_iso) if decision else timestamp_iso,
                "symbol": symbol,
                "raw_response": str(raw_output or "").strip()
            }
            if final_id:
                decision_record["ID"] = final_id

            if decision:
                decision_record.update({
                    "action": decision.get("action", "WAIT"),
                    "expiry_minutes": decision.get("expiry_minutes", 5),
                    "confidence_score": decision.get("confidence_score", 0),
                    "engine_used": decision.get("engine_used", "AI (Gemini)")
                })
            else:
                decision_record.update({
                    "action": "PENDING_PARSE",
                    "expiry_minutes": 5,
                    "confidence_score": 0,
                    "engine_used": "AI (Gemini)"
                })

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(decision_record, f, ensure_ascii=False, indent=2)

            logger.info(f"[SystemPrompt] Saved AI Order Decision file to: {file_path}")

            cls._enforce_retention_pattern(symbol_dir, "*.json")
            return file_path
        except Exception as e:
            logger.error(f"[SystemPrompt] Could not save AI Order Decision file for {symbol}: {e}", exc_info=True)
            return file_path or ""

    @classmethod
    def _save_decision_txt(
        cls,
        symbol: str,
        raw_output: str,
        analysis_id: str
    ) -> str:
        """
        Saves raw AI response text to data_base/ai_decision_output/<SYMBOL>/<analysis_id>.txt As-Is 100%.
        No YAML header/wrapper added.
        Enforces retention of max 30 .txt files per symbol.
        """
        try:
            symbol_dir = os.path.join(cls.AI_DECISION_OUTPUT_BASE_DIR, symbol)
            os.makedirs(symbol_dir, exist_ok=True)
            txt_path = os.path.join(symbol_dir, f"{analysis_id}.txt")

            content = str(raw_output or "").strip()

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(content)

            cls._enforce_retention_pattern(symbol_dir, "*.txt")
            logger.info(f"[SystemPrompt] Saved AI Raw Output txt to: {txt_path}")
            return txt_path
        except Exception as e:
            logger.error(f"[SystemPrompt] Could not save AI Raw Output txt for {symbol}: {e}", exc_info=True)
            return ""

    @classmethod
    def _enforce_retention_pattern(cls, symbol_dir: str, pattern: str) -> None:
        """Keeps at most MAX_RETENTION_FILES in the symbol directory for the specified pattern."""
        try:
            files = sorted(
                glob.glob(os.path.join(symbol_dir, pattern)),
                key=os.path.getmtime
            )
            while len(files) > cls.MAX_RETENTION_FILES:
                oldest = files.pop(0)
                try:
                    os.remove(oldest)
                    logger.debug(f"[SystemPrompt] Retention cleanup removed: {oldest}")
                except Exception as e:
                    logger.warning(f"[SystemPrompt] Could not remove old file {oldest}: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"[SystemPrompt] Error during retention cleanup: {e}", exc_info=True)

    @classmethod
    def _save_decision_csv(
        cls,
        symbol: str,
        decision: Dict[str, Any],
        analysis_id: Optional[str] = None,
        timestamp_str: Optional[str] = None
    ) -> str:
        """
        Appends the AI decision record into CSV files:
        1. data_base/ai_decision_output/<SYMBOL>/decisions.csv (Standard SSOT CSV)
        2. logs/logs_data_trade/ai_decisions/<SYMBOL>/<SYMBOL>_decisions.csv (Audit Log)
        3. data_base/ai_decision_output/<SYMBOL>/<SYMBOL>_decisions.csv (Compatibility)

        Header: timestamp,ID,symbol,action,confidence_score,expiry_minutes,engine_used,reason_th
        """
        last_csv_path = ""
        try:
            # 1. timestamp
            if timestamp_str and isinstance(timestamp_str, str) and timestamp_str.strip():
                now_utc_str = timestamp_str.strip()
            elif decision.get("timestamp"):
                now_utc_str = str(decision.get("timestamp")).strip()
            else:
                now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")

            # 2. action: CALL, PUT, WAIT
            raw_act = decision.get("action", "WAIT")
            act_clean = str(raw_act).strip().replace('"', '').replace("'", "").upper()
            if "CALL" in act_clean or "BUY" in act_clean:
                act_str = "CALL"
            elif "PUT" in act_clean or "SELL" in act_clean:
                act_str = "PUT"
            else:
                act_str = "WAIT"

            # 3. expiry: fixed at 5 minutes because the strategy uses M5 candles.
            raw_exp = decision.get("expiry_minutes") if decision.get("expiry_minutes") is not None else decision.get("expiry", 5)
            try:
                exp_val = max(1, min(5, int(raw_exp)))
            except (ValueError, TypeError):
                exp_val = 1

            # 4. confidence: float / int
            raw_conf = decision.get("confidence_score") if decision.get("confidence_score") is not None else decision.get("confidence", 0)
            try:
                c_float = float(raw_conf)
                conf_val = int(round(c_float)) if c_float.is_integer() else round(c_float, 2)
            except (ValueError, TypeError):
                conf_val = 0

            # 5. ID
            final_id = analysis_id or decision.get("ID") or decision.get("id")
            if not final_id:
                clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
                ts_mmdd = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
                final_id = f"{clean_sym}{ts_mmdd}"

            # 6. engine_used
            engine_used = decision.get("engine_used", "AI (Gemini)")

            # 7. reason_th
            reason_th = decision.get("reason_th", "")

            # Target 1: data_base/ai_decision_output/<SYMBOL>/decisions.csv (Standard SSOT CSV)
            symbol_dir = os.path.join(cls.AI_DECISION_OUTPUT_BASE_DIR, symbol)
            os.makedirs(symbol_dir, exist_ok=True)
            std_csv_path = os.path.join(symbol_dir, "decisions.csv")
            std_fieldnames = [
                "timestamp", "ID", "symbol", "action", "confidence_score",
                "expiry_minutes", "engine_used", "reason_th"
            ]
            std_file_exists = os.path.isfile(std_csv_path) and os.path.getsize(std_csv_path) > 0
            with open(std_csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=std_fieldnames)
                if not std_file_exists:
                    writer.writeheader()
                writer.writerow({
                    "timestamp": now_utc_str,
                    "ID": final_id,
                    "symbol": symbol,
                    "action": act_str,
                    "confidence_score": conf_val,
                    "expiry_minutes": exp_val,
                    "engine_used": engine_used,
                    "reason_th": reason_th
                })
            last_csv_path = std_csv_path

            # Target 2 & 3: Compatibility & audit logs
            legacy_targets = [
                (os.path.join("logs", "logs_data_trade", "ai_decisions", symbol), f"{symbol}_decisions.csv"),
                (symbol_dir, f"{symbol}_decisions.csv")
            ]
            for l_dir, l_name in legacy_targets:
                os.makedirs(l_dir, exist_ok=True)
                l_path = os.path.join(l_dir, l_name)
                l_exists = os.path.isfile(l_path) and os.path.getsize(l_path) > 0
                with open(l_path, mode="a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=std_fieldnames)
                    if not l_exists:
                        writer.writeheader()
                    writer.writerow({
                        "timestamp": now_utc_str,
                        "ID": final_id,
                        "symbol": symbol,
                        "action": act_str,
                        "confidence_score": conf_val,
                        "expiry_minutes": exp_val,
                        "engine_used": engine_used,
                        "reason_th": reason_th
                    })

            logger.info(f"[SystemPrompt] Appended decision to CSV: {std_csv_path}")
            return last_csv_path
        except Exception as e:
            logger.warning(f"[SystemPrompt] Could not write decision CSV for {symbol}: {e}", exc_info=True)
            return last_csv_path

    @classmethod
    async def _process_single_async(
        cls,
        symbol: str,
        prompt_filepath: Optional[str],
        payload_text: Optional[str],
        agent: Any
    ) -> Dict[str, Any]:
        """
        Async coroutine: processes one currency pair concurrently.
        1. Reads Part 2 payload → builds prompt
        2. Step 1: Sends to AI async → receives raw output (raw_output)
        3. Step 2: Parses raw text into structured JSON (parse_json_decision)
        4. Step 3: Saves decision to data_base/ai_decision_output/<SYMBOL>/<ID>.txt and decisions.csv
        5. Step 4: Returns structured JSON decision to executor_manager.py.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError(f"FAIL-FAST [async]: symbol must be non-empty string, got: {symbol!r}")
        if payload_text is not None and not isinstance(payload_text, str):
            raise TypeError(f"FAIL-FAST [async]: payload_text must be string for {symbol}")
        if not payload_text:
            if not prompt_filepath or not isinstance(prompt_filepath, str):
                raise ValueError(
                    f"FAIL-FAST [async]: prompt_filepath or payload_text required for {symbol}"
                )
            payload_text = cls.read_payload_from_disk(prompt_filepath)
        payload_text, _ = sanitize_payload_text(
            payload_text, source=prompt_filepath or "in-memory"
        )
        analysis_id, prompt_ts = cls._extract_meta_from_payload(payload_text, prompt_filepath)
        now_utc = datetime.now(timezone.utc)
        utc_timestamp_str = prompt_ts or now_utc.strftime("%Y-%m-%d %H:%M:%S+00:00")
        if not analysis_id:
            ts_mmdd = now_utc.strftime("%m%d%H%M%S")
            clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
            analysis_id = f"{clean_sym}{ts_mmdd}"

        from config_setting.config_loader import load_settings
        cfg = load_settings(reload=False)
        stake = float(cfg.get("account", {}).get("stake_per_trade", 35.0))
        min_conf = float(cfg.get("ai_mode", {}).get("min_confidence", cfg.get("ml_mode", {}).get("min_confidence", 60.0)))

        system_instruction = cls.get_system_prompt()
        user_prompt = cls.build_user_prompt(symbol, payload_text)

        # ── Step 1: รับคำตอบดิบ (raw_output) จาก AI ──────────────────────────────────
        raw_output = await agent.send_prompt_async(
            user_prompt=user_prompt,
            system_instruction=system_instruction
        )

        # ── Step 2: บันทึกคำตอบดิบทันที As-Is (100%) ─────────────────────────────────
        cls._save_decision_txt(
            symbol=symbol,
            raw_output=raw_output,
            analysis_id=analysis_id
        )

        # ── Step 3: แกะกล่อง (Parse) ให้เป็น JSON ตามฟอร์ม (parse_json_decision) ───────
        decision = cls.parse_json_decision(
            raw_output=raw_output,
            symbol=symbol,
            ai_agent=agent,
            analysis_id=analysis_id,
            utc_timestamp_str=utc_timestamp_str
        )

        final_id = decision.get("ID") or analysis_id

        # ── บันทึกผลการวิเคราะห์ลง CSV สำหรับระบบเทรดและสถิติ ──────────────────────
        cls._save_decision_csv(
            symbol=symbol,
            decision=decision,
            analysis_id=final_id,
            timestamp_str=utc_timestamp_str
        )

        logger.info(
            f"[SystemPrompt Concurrent] {symbol} ✓ ID={final_id} "
            f"Action={decision.get('action')} Confidence={decision.get('confidence_score')}"
        )

        # ── Step 4: คืนค่า (return) JSON decision ส่งต่อให้ executor_manager.py ────────
        return decision

    @classmethod
    def process_ai_decisions_concurrent(
        cls,
        tasks: list
    ) -> Dict[str, Dict[str, Any]]:
        """
        N-Symbol Concurrent Dispatch:
        Fires Gemini API for ALL symbols simultaneously via asyncio.gather().
        Works for N=1 to N=10+ symbols — no sequential waiting.
        """
        import concurrent.futures
        import traceback

        if not tasks or not isinstance(tasks, list):
            raise ValueError(
                "FAIL-FAST: tasks must be a non-empty list of "
                "(symbol, filepath[, payload_text]) tuples"
            )

        normalized_tasks = []
        for task in tasks:
            if not isinstance(task, (tuple, list)) or len(task) not in (2, 3):
                raise ValueError(
                    "FAIL-FAST: each AI task must be "
                    "(symbol, filepath) or (symbol, filepath, payload_text)"
                )
            task_symbol, task_filepath = task[0], task[1]
            task_payload = task[2] if len(task) == 3 else None
            if not isinstance(task_symbol, str) or not task_symbol:
                raise ValueError("FAIL-FAST: AI task symbol must be a non-empty string")
            if task_filepath is not None and not isinstance(task_filepath, str):
                raise TypeError("FAIL-FAST: AI task filepath must be a string or None")
            if task_payload is not None and not isinstance(task_payload, str):
                raise TypeError("FAIL-FAST: AI task payload_text must be a string or None")
            normalized_tasks.append((task_symbol, task_filepath, task_payload))

        symbols_list = [t[0] for t in normalized_tasks]
        logger.info(
            f"[SystemPrompt Concurrent] Dispatching {len(tasks)} symbol(s) simultaneously on dedicated 1:1 channels: {symbols_list}"
        )

        async def _gather_all():
            coroutines = [
                cls._process_single_async(sym, fp, payload, cls.get_dedicated_agent(sym))
                for sym, fp, payload in normalized_tasks
            ]
            return await asyncio.gather(*coroutines, return_exceptions=True)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, _gather_all())
                    raw_results = future.result(timeout=60)
            else:
                raw_results = loop.run_until_complete(_gather_all())
        except RuntimeError:
            raw_results = asyncio.run(_gather_all())

        output: Dict[str, Dict[str, Any]] = {}
        for (symbol, _, _), result in zip(normalized_tasks, raw_results):
            if isinstance(result, Exception):
                logger.error(
                    f"[SystemPrompt Concurrent] {symbol} FAILED during concurrent dispatch: {result}",
                    exc_info=(type(result), result, result.__traceback__)
                )
                traceback.print_exception(type(result), result, result.__traceback__)
                raise RuntimeError(
                    f"FAIL-FAST: AI analysis failed for {symbol}; trading halted"
                ) from result
            else:
                output[symbol] = result

        logger.info(
            f"[SystemPrompt Concurrent] Completed {len(output)} symbol(s): {list(output.keys())}"
        )

        # แสดงผลสรุปบน Console Dashboard ทันทีที่ AI วิเคราะห์และบันทึก CSV ครบทุกคู่เงิน
        from monitoring.console_dashboard import ConsoleUI
        ConsoleUI.show_ai_analysis_complete(output)

        return output

    @classmethod
    def parse_json_decision(
        cls,
        raw_output: str,
        symbol: str,
        ai_agent: Any,
        analysis_id: Optional[str] = None,
        utc_timestamp_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """Extracts, parses, and normalizes JSON decision."""
        if not raw_output or not isinstance(raw_output, str):
            raise ValueError("FAIL-FAST: Received empty text response from AI transport agent")

        clean_text = raw_output.strip()
        start_idx = clean_text.find('{')
        end_idx = clean_text.rfind('}')

        if start_idx == -1 or end_idx == -1:
            raise ValueError(f"FAIL-FAST: No JSON object found in AI response: {clean_text}")

        json_str = clean_text[start_idx:end_idx + 1]
        try:
            decision = json.loads(json_str)
        except Exception as e:
            raise ValueError(f"FAIL-FAST: Invalid JSON format from AI response ({json_str}): {e}") from e

        if not isinstance(decision, dict):
            raise TypeError(f"FAIL-FAST: Expected JSON dictionary from AI, got {type(decision)}")

        # ── Action Resolution ────────────────────────────────────────────────
        raw_act = decision.get("action") or decision.get("direction") or decision.get("signal") or ""
        norm_action = str(raw_act).strip().replace('"', '').replace("'", "").upper()
        if "CALL" in norm_action or "BUY" in norm_action:
            norm_action = "CALL"
        elif "PUT" in norm_action or "SELL" in norm_action:
            norm_action = "PUT"
        else:
            norm_action = "WAIT"

        # ── Confidence Score Resolution ──────────────────────────────────────
        raw_conf = decision.get("confidence_score")
        if raw_conf is None:
            raw_conf = decision.get("confidence") or decision.get("score") or 50.0
        try:
            norm_confidence = float(raw_conf)
            norm_confidence = max(0.0, min(100.0, norm_confidence))
        except (ValueError, TypeError):
            raise ValueError(
                f"FAIL-FAST: Invalid confidence_score from AI: {raw_conf!r}"
            )

        # ── Expiry Resolution ────────────────────────────────────────────────
        raw_expiry = decision.get("expiry_minutes") or decision.get("expiry") or 5
        try:
            norm_expiry = int(raw_expiry)
            if norm_expiry != 5:
                raise ValueError("Binary Options expiry must be exactly 5 minutes for M5 strategy")
        except (ValueError, TypeError):
            raise ValueError(
                f"FAIL-FAST: Invalid expiry_minutes={raw_expiry}; "
                "this M5 strategy requires exactly 5 minutes"
            )

        # ── ID Resolution & Verification ────────────────────────────────────
        ai_returned_id = decision.get("ID") or decision.get("id")
        final_id = str(ai_returned_id).strip() if ai_returned_id is not None else ""

        if final_id:
            if analysis_id and final_id != analysis_id:
                logger.warning(
                    f"[SystemPrompt] AI returned ID '{final_id}' differs from original source ID '{analysis_id}'. Using AI returned ID as primary."
                )
        else:
            final_id = analysis_id or ""
            if not final_id:
                ts_mmdd = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
                clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
                final_id = f"{clean_sym}{ts_mmdd}"

        reason_th = str(decision.get("reason_th") or decision.get("reason") or "").strip()

        model_label = getattr(ai_agent, "model_name", type(ai_agent).__name__)

        if not utc_timestamp_str:
            utc_timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")

        return {
            "ID": final_id,
            "symbol": str(decision.get("symbol") or decision.get("asset") or symbol).strip(),
            "action": norm_action,
            "expiry_minutes": norm_expiry,
            "suggested_expiry_minutes": norm_expiry,
            "confidence_score": norm_confidence,
            "reason_th": reason_th,
            "engine_used": f"AI ({model_label})",
            "timestamp": utc_timestamp_str
        }
