"""
System Prompt & Prompt Formatter for Part 3 AI Decision Engine
==============================================================
Defines the authoritative System Prompt and Strict JSON Output Specification
for DeepSeek Browser Agent and Google Gemini API, with automatic prompt archiving
to `data_trade/ai_decision/ai_prompt_output/<SYMBOL>/` retaining max 30 files per symbol.
"""

import os
import asyncio
import csv
import glob
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """:: คำสั่ง ::
จงทำหน้าที่เป็น Quantitative Trading AI และ Binary Options Expert 
วิเคราะห์ข้อมูลตลาดแบบ Multi-Timeframe (M1, M5, M15) ด้านล่างนี้ โดยประมวลผลทุกตัวชี้วัด (Price Action, Technical Indicators, Volume, Market Context, Multi-Timeframe Alignment) 
เพื่อกำหนด Action, Expiry Minutes (1-5 นาที), และ Confidence Score
ให้พิจารณาระยะเวลาถือครอง expiry_minutes 1-5 นาที ซึ่งผลแพ้ชนะเทียบเท่าข้อมูลจากอินดิเคเตอร์
หากสัญญาณไม่ชัดเจนหรือมีความเสี่ยงสูง ให้ตอบ "action": "WAIT"

:: ข้อกำหนดการส่งผลลัพธ์ ::
- ตอบกลับในรูปแบบ JSON ตามโครงสร้างนี้เท่านั้น (ห้ามมีข้อความเกริ่นนำหรือปิดท้ายนอก JSON):
{
  "symbol": "string",
  "action": "CALL" | "PUT" | "WAIT",
  "expiry_minutes": 1,
  "confidence_score": 0
}"""


class SystemPrompt:
    """
    Prompt Orchestrator & Response Parser for Part 3.
    Receives 100-line payload, formats complete prompt, archives prompt to
    data_trade/ai_decision/ai_prompt_output/<SYMBOL>/, sends to AI transport agent, parses raw response,
    and returns validated decision JSON.
    """

    MAX_RETENTION_FILES = 30
    AI_DECISION_OUTPUT_BASE_DIR = os.path.join("data_trade", "ai_decision_output")
    _CHANNEL_POOL: Optional[Any] = None

    # ── BOSS ORDER: Disable JSON decision file write ──────────────────────
    # CSV recording via _save_decision_csv() remains active for audit/statistics.
    # To re-enable: set ENABLE_DECISION_JSON = True
    ENABLE_DECISION_JSON: bool = False

    @classmethod
    def prewarm_and_test_ai(cls, symbols: list) -> bool:
        """Pre-warms and tests dedicated AI channels for all symbols."""
        from data_trade.ai_analysis.gemini_bridge import DedicatedGeminiManager
        from config_setting.config_loader import load_settings
        cfg = load_settings(reload=False).get("ai_mode", {})
        model_name = cfg.get("gemini_model", "gemini-3.5-flash-lite")
        return DedicatedGeminiManager.test_connection(symbols=symbols, model_name=model_name)

    @classmethod
    def get_dedicated_agent(cls, symbol: str) -> Any:
        """Returns the dedicated 1:1 agent for a specific symbol."""
        from data_trade.ai_analysis.gemini_bridge import DedicatedGeminiManager
        return DedicatedGeminiManager.get_agent(symbol)

    @classmethod
    def get_channel_pool(cls) -> Any:
        """Legacy alias — returns DedicatedGeminiManager."""
        from data_trade.ai_analysis.gemini_bridge import DedicatedGeminiManager
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

        return (
            f":: ข้อมูลตลาดสำหรับวิเคราะห์ ::\n"
            f"{prompt_text.strip()}\n"
        )

    @classmethod
    def read_payload_from_disk(cls, prompt_filepath: str) -> str:
        """Reads 100-line prompt text from Part 2 output file on disk."""
        if not prompt_filepath or not isinstance(prompt_filepath, str):
            raise ValueError("FAIL-FAST: prompt_filepath must be a non-empty string")
        if not os.path.isfile(prompt_filepath):
            raise FileNotFoundError(f"FAIL-FAST: Payload file not found at {prompt_filepath}")

        with open(prompt_filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            raise ValueError(f"FAIL-FAST: Payload file is empty at {prompt_filepath}")
        return content

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
        1. Reads 100-line payload from disk (prompt_filepath) if provided, or uses payload_text.
        2. Builds complete prompt with system rules.
        3. Archives assembled prompt to data_trade/ai_decision/ai_prompt_output/<SYMBOL>/<FILENAME>.txt.
        4. Step 1: Receives raw output (raw_output) from AI transport agent.
        5. Step 2: Saves raw output and data into folder data_trade/ai_output/<SYMBOL>/.
        6. Step 3: Parses raw output into JSON decision (parse_json_decision).
        7. Step 4: Returns structured JSON decision to executor_manager.py.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("FAIL-FAST: symbol must be a non-empty string")

        if prompt_filepath:
            payload_text = cls.read_payload_from_disk(prompt_filepath)
        elif not payload_text or not isinstance(payload_text, str):
            raise ValueError("FAIL-FAST: Either prompt_filepath or non-empty payload_text must be provided")

        now_utc = datetime.now(timezone.utc)
        utc_timestamp_str = now_utc.strftime("%Y-%m-%d %H:%M:%S+00:00")
        ts_mmdd = now_utc.strftime("%m%d%H%M%S")
        clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
        analysis_id = f"{clean_sym}{ts_mmdd}"

        target_agent = ai_agent
        _acquired_from_pool = False
        if target_agent is None:
            target_agent = cls.get_channel_pool().acquire()
            _acquired_from_pool = True

        if target_agent is None:
            fallback_decision = {
                "symbol": symbol,
                "action": "WAIT",
                "expiry_minutes": 1,
                "confidence_score": 0,
                "engine_used": "DISABLED",
                "timestamp": utc_timestamp_str,
                "ID": analysis_id
            }
            cls._save_decision_csv(symbol=symbol, decision=fallback_decision, analysis_id=analysis_id, timestamp_str=utc_timestamp_str)
            return fallback_decision


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

            # ── Step 2: บันทึกคำตอบดิบและข้อมูลลงโฟลเดอร์ data_trade/ai_output/<SYMBOL>/ ─────
            saved_output_file = cls._save_decision_file(
                symbol=symbol,
                raw_output=raw_output,
                decision=None,
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

            # Update decision file with parsed JSON decision data and save CSV record
            cls._save_decision_file(
                symbol=symbol,
                raw_output=raw_output,
                decision=parsed_decision,
                file_path=saved_output_file,
                analysis_id=analysis_id
            )
            cls._save_decision_csv(
                symbol=symbol,
                decision=parsed_decision,
                analysis_id=analysis_id,
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
                    "expiry_minutes": decision.get("expiry_minutes", 1),
                    "confidence_score": decision.get("confidence_score", 0),
                    "engine_used": decision.get("engine_used", "AI (Gemini)")
                })
            else:
                decision_record.update({
                    "action": "PENDING_PARSE",
                    "expiry_minutes": 1,
                    "confidence_score": 0,
                    "engine_used": "AI (Gemini)"
                })


            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(decision_record, f, ensure_ascii=False, indent=2)

            logger.info(f"[SystemPrompt] Saved AI Order Decision file to: {file_path}")

            # Enforce 30-file retention for decision files
            cls._enforce_retention_pattern(symbol_dir, "*.json")
            return file_path
        except Exception as e:
            logger.error(f"[SystemPrompt] Could not save AI Order Decision file for {symbol}: {e}", exc_info=True)
            return file_path or ""

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
    def _ensure_csv_header(cls, csv_path: str, expected_header: list) -> None:
        """
        Checks if csv_path exists and has the old header format.
        If it has an old header, migrates existing data rows to match the new header structure.
        Header: timestamp,action,expiry,confidence,ID
        """
        if not os.path.isfile(csv_path) or os.path.getsize(csv_path) == 0:
            return

        try:
            with open(csv_path, mode="r", encoding="utf-8-sig") as f:
                reader = list(csv.reader(f))

            if not reader:
                return

            header = [h.strip() for h in reader[0]]

            if header == expected_header:
                return

            migrated_rows = []
            for row in reader[1:]:
                if not row or len(row) < 5:
                    continue
                ts, sym, act, exp, conf = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip(), row[4].strip()

                if not ts.endswith("+00:00"):
                    ts_iso = f"{ts}+00:00"
                else:
                    ts_iso = ts

                clean_sym = sym.replace("/", "").replace("-", "").replace("_", "")
                ts_digits = "".join(c for c in ts if c.isdigit())
                if len(ts_digits) >= 14:
                    ts_mmdd = ts_digits[4:14]
                elif len(ts_digits) >= 10:
                    ts_mmdd = ts_digits[-10:]
                else:
                    ts_mmdd = datetime.now(timezone.utc).strftime("%m%d%H%M%S")

                row_id = f"{clean_sym}{ts_mmdd}"

                migrated_rows.append({
                    "timestamp": ts_iso,
                    "action": act,
                    "expiry": exp,
                    "confidence": conf,
                    "ID": row_id
                })

            with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=expected_header)
                writer.writeheader()
                for m_row in migrated_rows:
                    writer.writerow(m_row)

            logger.info(f"[SystemPrompt] Migrated CSV header and {len(migrated_rows)} rows in {csv_path}")
        except Exception as e:
            logger.warning(f"[SystemPrompt] CSV header migration check failed for {csv_path}: {e}")

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
        1. logs/logs_data_trade/ai_decisions/<SYMBOL>/<SYMBOL>_decisions.csv
        2. data_trade/ai_output/<SYMBOL>/<SYMBOL>_decisions.csv

        Header: timestamp,action,expiry,confidence,ID
        Example: 2026-08-21 12:01:00+00:00, CALL, 4, 85, EURUSD0821231003
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

            # 3. expiry: int 1-5
            raw_exp = decision.get("expiry_minutes") if decision.get("expiry_minutes") is not None else decision.get("expiry", 1)
            try:
                exp_val = max(1, min(5, int(raw_exp)))
            except (ValueError, TypeError):
                exp_val = 1

            # 4. confidence: int/float (e.g. 85)
            raw_conf = decision.get("confidence_score") if decision.get("confidence_score") is not None else decision.get("confidence", 0)
            try:
                c_float = float(raw_conf)
                conf_val = int(round(c_float)) if c_float.is_integer() else round(c_float, 2)
            except (ValueError, TypeError):
                conf_val = 0

            # 5. ID: symbol + MMDDHHMMSS (e.g. EURUSD0821231003)
            final_id = analysis_id or decision.get("ID") or decision.get("id")
            if not final_id:
                clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
                ts_mmdd = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
                final_id = f"{clean_sym}{ts_mmdd}"

            fieldnames = ["timestamp", "action", "expiry", "confidence", "ID"]
            row = {
                "timestamp": now_utc_str,
                "action": act_str,
                "expiry": exp_val,
                "confidence": conf_val,
                "ID": final_id
            }

            target_dirs = [
                os.path.join("logs", "logs_data_trade", "ai_decisions", symbol),
                os.path.join(cls.AI_DECISION_OUTPUT_BASE_DIR, symbol)
            ]

            for target_dir in target_dirs:
                os.makedirs(target_dir, exist_ok=True)
                csv_path = os.path.join(target_dir, f"{symbol}_decisions.csv")

                cls._ensure_csv_header(csv_path, fieldnames)

                file_exists = os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0

                with open(csv_path, mode="a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row)

                last_csv_path = csv_path
                logger.info(f"[SystemPrompt] Appended decision to CSV: {csv_path}")

            return last_csv_path
        except Exception as e:
            logger.warning(f"[SystemPrompt] Could not write decision CSV for {symbol}: {e}", exc_info=True)
            return last_csv_path

    @classmethod
    async def _process_single_async(
        cls,
        symbol: str,
        prompt_filepath: str,
        agent: Any
    ) -> Dict[str, Any]:
        """
        Async coroutine: processes one currency pair concurrently.
        1. Reads Part 2 payload → builds prompt → saves to ai_prompt_output
        2. Step 1: Sends to AI async → receives raw output (raw_output)
        3. Step 2: Saves raw output and data into folder data_trade/ai_output/<SYMBOL>/
        4. Step 3: Parses raw text into structured JSON (parse_json_decision)
        5. Step 4: Returns structured JSON decision to executor_manager.py.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError(f"FAIL-FAST [async]: symbol must be non-empty string, got: {symbol!r}")
        if not prompt_filepath or not isinstance(prompt_filepath, str):
            raise ValueError(f"FAIL-FAST [async]: prompt_filepath must be non-empty string for {symbol}")

        now_utc = datetime.now(timezone.utc)
        utc_timestamp_str = now_utc.strftime("%Y-%m-%d %H:%M:%S+00:00")
        ts_mmdd = now_utc.strftime("%m%d%H%M%S")
        clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
        analysis_id = f"{clean_sym}{ts_mmdd}"

        payload_text = cls.read_payload_from_disk(prompt_filepath)
        system_instruction = cls.get_system_prompt()
        user_prompt = cls.build_user_prompt(symbol, payload_text)

        # ── Step 1: รับคำตอบดิบ (raw_output) จาก AI ──────────────────────────────────
        raw_output = await agent.send_prompt_async(
            user_prompt=user_prompt,
            system_instruction=system_instruction
        )

        # ── Step 2: บันทึกคำตอบดิบและข้อมูลลงโฟลเดอร์ data_trade/ai_output/<SYMBOL>/ ─────
        saved_output_file = cls._save_decision_file(
            symbol=symbol,
            raw_output=raw_output,
            decision=None,
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

        # Update decision file with parsed JSON decision data and save CSV record
        cls._save_decision_file(
            symbol=symbol,
            raw_output=raw_output,
            decision=decision,
            file_path=saved_output_file,
            analysis_id=analysis_id
        )
        cls._save_decision_csv(
            symbol=symbol,
            decision=decision,
            analysis_id=analysis_id,
            timestamp_str=utc_timestamp_str
        )

        logger.info(
            f"[SystemPrompt Concurrent] {symbol} ✓ "
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
            raise ValueError("FAIL-FAST: tasks must be a non-empty list of (symbol, filepath) tuples")

        symbols_list = [t[0] for t in tasks]
        logger.info(
            f"[SystemPrompt Concurrent] Dispatching {len(tasks)} symbol(s) simultaneously on dedicated 1:1 channels: {symbols_list}"
        )

        async def _gather_all():
            coroutines = [
                cls._process_single_async(sym, fp, cls.get_dedicated_agent(sym))
                for sym, fp in tasks
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
        for (symbol, _), result in zip(tasks, raw_results):
            if isinstance(result, Exception):
                logger.error(
                    f"[SystemPrompt Concurrent] {symbol} FAILED during concurrent dispatch: {result}",
                    exc_info=(type(result), result, result.__traceback__)
                )
                traceback.print_exception(type(result), result, result.__traceback__)
                output[symbol] = {
                    "symbol": symbol,
                    "action": "WAIT",
                    "expiry_minutes": 1,
                    "confidence_score": 0,
                    "engine_used": "FALLBACK_SAFE_WAIT"
                }
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
            norm_confidence = 50.0

        # ── Expiry Resolution ────────────────────────────────────────────────
        raw_expiry = decision.get("expiry_minutes") or decision.get("expiry") or 1
        try:
            norm_expiry = int(raw_expiry)
            norm_expiry = max(1, min(5, norm_expiry))
        except (ValueError, TypeError):
            norm_expiry = 1

        model_label = getattr(ai_agent, "model_name", type(ai_agent).__name__)

        if not analysis_id:
            ts_mmdd = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
            clean_sym = symbol.replace("/", "").replace("-", "").replace("_", "")
            analysis_id = f"{clean_sym}{ts_mmdd}"

        if not utc_timestamp_str:
            utc_timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")

        return {
            "symbol": str(decision.get("symbol") or decision.get("asset") or symbol).strip(),
            "action": norm_action,
            "expiry_minutes": norm_expiry,
            "confidence_score": norm_confidence,
            "engine_used": f"AI ({model_label})",
            "timestamp": utc_timestamp_str,
            "ID": analysis_id
        }
