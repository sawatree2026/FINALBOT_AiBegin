"""
Gemini API Transport Driver for Part 3
=======================================
Pure transport layer: sends prompt → returns raw text response.
Only model       : gemini-3.5-flash-lite (Daily Limit: 500)
No model fallback; failures are reported immediately.
Supports both synchronous (send_prompt) and asynchronous (send_prompt_async) dispatch.
"""

import os
import time
import asyncio
import threading
import concurrent.futures
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

PRIMARY_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = PRIMARY_MODEL
PRIMARY_DAILY_LIMIT = 500
SECONDARY_DAILY_LIMIT = 0

_FALLBACK_TRIGGERS = [
    "404", "not_found", "not found",
    "503", "high demand", "unavailable",
    "resource_exhausted", "429", "rate", "quota"
]


def get_gemini_api_keys() -> List[str]:
    """
    Retrieves Gemini keys from environment only.
    Multiple numbered keys are used for per-symbol load distribution.
    """
    keys = [
        os.getenv(f"GEMINI_API_KEY_{index}", "").strip()
        for index in range(1, 4)
    ]
    keys = [key for key in keys if key]
    if not keys:
        legacy_key = os.getenv("GEMINI_API_KEY", "").strip()
        if legacy_key:
            keys = [legacy_key]
    if not keys:
        raise ValueError(
            "FAIL-FAST: Set GEMINI_API_KEY_1, GEMINI_API_KEY_2, or GEMINI_API_KEY_3 "
            "in the process environment."
        )
    return keys


def get_gemini_api_key() -> str:
    """Backward-compatible single-key accessor."""
    return get_gemini_api_keys()[0]


def get_gemini_config() -> Dict[str, Any]:
    """
    Loads Gemini AI settings from settings.json.
    """
    try:
        from config_setting.config_loader import load_settings
        cfg = load_settings(reload=False).get("ai_mode", {})
    except Exception:
        cfg = {}

    primary_model = PRIMARY_MODEL
    primary_limit = int(cfg.get("primary_daily_limit", PRIMARY_DAILY_LIMIT))
    secondary_model = PRIMARY_MODEL
    secondary_limit = 0

    return {
        "primary_model": primary_model,
        "primary_daily_limit": primary_limit,
        "secondary_model": secondary_model,
        "secondary_daily_limit": secondary_limit,
    }


class DailyQuotaTracker:
    """
    Singleton Daily Quota Tracker across all symbol channels and API agents.
    Tracks the single permitted Gemini model and resets its daily quota.
    """
    _instance: Optional["DailyQuotaTracker"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DailyQuotaTracker, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._current_date = self._get_today_str()
        self._primary_count = 0
        self._secondary_count = 0
        self._primary_rate_limited = False
        self._secondary_rate_limited = False
        self._sync_config()

    @staticmethod
    def _get_today_str() -> str:
        """Returns the current date string (YYYY-MM-DD) in local timezone."""
        return datetime.now().strftime("%Y-%m-%d")

    def _sync_config(self) -> None:
        """Syncs model names and limits from settings."""
        cfg = get_gemini_config()
        self.primary_model = cfg["primary_model"]
        self.primary_limit = cfg["primary_daily_limit"]
        self.secondary_model = cfg["secondary_model"]
        self.secondary_limit = cfg["secondary_daily_limit"]

    def _check_and_reset_if_new_day(self) -> None:
        """Checks if a new calendar day has started, and resets counters."""
        today = self._get_today_str()
        if today != self._current_date:
            logger.info(
                f"[DailyQuotaTracker] New day detected ({self._current_date} -> {today}). "
                f"Resetting daily quota counters (Previous: {self.primary_model}={self._primary_count}/{self.primary_limit}, "
                f"{self.secondary_model}={self._secondary_count}/{self.secondary_limit})."
            )
            self._current_date = today
            self._primary_count = 0
            self._secondary_count = 0
            self._primary_rate_limited = False
            self._secondary_rate_limited = False
            self._sync_config()

    def get_active_model_chain(self, requested_model: Optional[str] = None) -> List[str]:
        """
        Determines the ordered list of models to try for the next request.
        Only the configured Gemini 3.5 Flash Lite model is eligible.
        """
        with self._lock:
            self._check_and_reset_if_new_day()
            self._sync_config()

            if requested_model and requested_model != PRIMARY_MODEL:
                raise ValueError(
                    f"FAIL-FAST: Unsupported Gemini model '{requested_model}'. "
                    f"Only '{PRIMARY_MODEL}' is permitted."
                )
            primary_ok = (
                not self._primary_rate_limited
                and self._primary_count < self.primary_limit
            )
            return [PRIMARY_MODEL] if primary_ok else []

    def record_success(self, model_name: str) -> None:
        """Records a successful request count for the given model."""
        with self._lock:
            self._check_and_reset_if_new_day()
            if model_name == self.primary_model:
                self._primary_count += 1
                count = self._primary_count
                limit = self.primary_limit
            elif model_name == self.secondary_model:
                self._secondary_count += 1
                count = self._secondary_count
                limit = self.secondary_limit
            else:
                self._primary_count += 1
                count = self._primary_count
                limit = self.primary_limit

            total_used = self._primary_count + self._secondary_count
            total_limit = self.primary_limit + self.secondary_limit
            logger.info(
                f"[DailyQuotaTracker] Model: {model_name} used ({count}/{limit}) | "
                f"Today Total: {total_used}/{total_limit} requests"
            )

    def record_exhausted_or_rate_limit(self, model_name: str, reason: str) -> None:
        """Marks a model as rate-limited or exhausted for the remainder of the day."""
        with self._lock:
            self._check_and_reset_if_new_day()
            if model_name == self.primary_model:
                self._primary_rate_limited = True
                logger.warning(
                    f"[DailyQuotaTracker] Only model '{model_name}' hit rate-limit/exhaustion ({reason}); "
                    "no fallback model is configured."
                )
            elif model_name == self.secondary_model:
                self._secondary_rate_limited = True
                logger.warning(
                    f"[DailyQuotaTracker] Secondary model '{model_name}' hit rate-limit/exhaustion ({reason}). "
                    f"All Gemini models are now exhausted for today ({self._primary_count + self._secondary_count}/1000 used)."
                )

    def get_status(self) -> Dict[str, Any]:
        """Returns the current daily quota status."""
        with self._lock:
            self._check_and_reset_if_new_day()
            self._sync_config()
            return {
                "date": self._current_date,
                "primary_model": self.primary_model,
                "primary_used": self._primary_count,
                "primary_limit": self.primary_limit,
                "primary_available": (not self._primary_rate_limited) and (self._primary_count < self.primary_limit),
                "secondary_model": self.secondary_model,
                "secondary_used": self._secondary_count,
                "secondary_limit": self.secondary_limit,
                "secondary_available": (not self._secondary_rate_limited) and (self._secondary_count < self.secondary_limit),
                "total_used": self._primary_count + self._secondary_count,
                "total_limit": self.primary_limit + self.secondary_limit,
            }


# Module-level singleton instance
quota_tracker = DailyQuotaTracker()


class GeminiApiAgent:
    """
    Pure Transport Driver for Google Gemini API.
    Responsible ONLY for sending prompt text and returning raw text response.
    Only model: gemini-3.5-flash-lite (500/day).
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        if api_key is not None and not isinstance(api_key, str):
            raise TypeError(f"FAIL-FAST: api_key must be a string, got {type(api_key)}")
        if model_name is not None and not isinstance(model_name, str):
            raise TypeError(f"FAIL-FAST: model_name must be a string, got {type(model_name)}")

        self.api_key = api_key or get_gemini_api_key()
        if not self.api_key:
            raise ValueError(
                "FAIL-FAST: No Gemini API key is available in the process environment."
            )

        cfg = get_gemini_config()
        self.model_name = model_name or cfg["primary_model"]

        try:
            self.client = genai.Client(api_key=self.api_key)
            logger.info(
                f"[GeminiApiAgent] Initialized | Model: {cfg['primary_model']} "
                f"(Limit: {cfg['primary_daily_limit']})"
            )
        except Exception as e:
            logger.exception("[GeminiApiAgent] Could not initialize Google GenAI client.")
            raise RuntimeError(f"FAIL-FAST: Google GenAI client initialization failed: {e}") from e

    def send_prompt(
        self,
        user_prompt: str,
        system_instruction: str = "",
        response_mime_type: Optional[str] = "application/json",
        temperature: float = 0.2
    ) -> str:
        """
        Synchronous dispatch to Gemini API.
        Uses only Gemini 3.5 Flash Lite. Quota or rate-limit errors fail fast.
        Supports both Trade Decision (application/json) and Natural Language Chat (text/plain or None).
        """
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("FAIL-FAST: user_prompt must be a non-empty string.")

        config_kwargs: Dict[str, Any] = {"temperature": temperature}
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        config = types.GenerateContentConfig(**config_kwargs)

        candidates = quota_tracker.get_active_model_chain(requested_model=self.model_name)
        if not candidates:
            status = quota_tracker.get_status()
            raise RuntimeError(
                f"FAIL-FAST: Daily Gemini API quota exhausted across all models "
                f"({status['total_used']}/{status['total_limit']} used today on {status['date']}). "
                f"Primary ({status['primary_model']}): {status['primary_used']}/{status['primary_limit']}, "
                f"Secondary ({status['secondary_model']}): {status['secondary_used']}/{status['secondary_limit']}."
            )

        last_err = None
        for model in candidates:
            try:
                logger.info(f"[GeminiApiAgent] Dispatching to model: {model}")
                response = self.client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config
                )
                txt = (response.text or "").strip()
                if txt:
                    quota_tracker.record_success(model)
                    self.model_name = model
                    logger.info(f"[GeminiApiAgent] Response received from: {model}")
                    return txt
                logger.warning(f"[GeminiApiAgent] Empty response from {model}")
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if any(t in err_str for t in _FALLBACK_TRIGGERS):
                    quota_tracker.record_exhausted_or_rate_limit(model, str(e))
                    logger.error(
                        f"[GeminiApiAgent] {model} hit rate-limit/fallback trigger ({e}); "
                        "no fallback model is configured."
                    )
                    raise RuntimeError(
                        f"FAIL-FAST: Gemini 3.5 Flash Lite unavailable: {e}"
                    ) from e
                logger.exception(f"[GeminiApiAgent] Non-recoverable error on {model}: {e}")
                raise RuntimeError(f"FAIL-FAST: Gemini API call failed: {e}") from e

        if last_err is not None:
            logger.error(
                f"[GeminiApiAgent] All candidate models exhausted. Last error: {last_err}",
                exc_info=(type(last_err), last_err, last_err.__traceback__)
            )
        else:
            logger.error("[GeminiApiAgent] All candidate models exhausted with no captured error.")
        raise RuntimeError(
            f"FAIL-FAST: Gemini API failed on all models [{', '.join(candidates)}]: {last_err}"
        ) from last_err

    async def send_prompt_async(
        self,
        user_prompt: str,
        system_instruction: str = "",
        response_mime_type: Optional[str] = "application/json",
        temperature: float = 0.2
    ) -> str:
        """
        Asynchronous dispatch — used by asyncio.gather() for N-symbol concurrent calls.
        Runs blocking send_prompt() in a thread pool executor to avoid blocking the event loop.
        """
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("FAIL-FAST: user_prompt must be a non-empty string.")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.send_prompt, user_prompt, system_instruction, response_mime_type, temperature
        )


class DedicatedGeminiManager:
    """
    Dedicated 1:1 Gemini API Channels for each trading symbol.
    Provides persistent, warm TCP/SSL connections permanently bound to each pair.
    """
    _agents: Dict[str, GeminiApiAgent] = {}
    _model_name: Optional[str] = None
    _key_index: int = 0
    _key_lock = threading.Lock()

    @classmethod
    def _next_api_key(cls) -> str:
        keys = get_gemini_api_keys()
        with cls._key_lock:
            key = keys[cls._key_index % len(keys)]
            cls._key_index += 1
        return key

    @classmethod
    def initialize(cls, symbols: List[str], model_name: Optional[str] = None) -> None:
        """Pre-warms and binds a dedicated channel for each symbol at startup."""
        cfg = get_gemini_config()
        cls._model_name = model_name or cfg["primary_model"]
        for sym in symbols:
            if sym not in cls._agents:
                cls._agents[sym] = GeminiApiAgent(
                    api_key=cls._next_api_key(),
                    model_name=cls._model_name
                )
        logger.info(
            f"[DedicatedGeminiManager] Initialized {len(cls._agents)} dedicated channels for: {list(cls._agents.keys())}"
        )

    @classmethod
    def test_connection(cls, symbols: List[str], model_name: Optional[str] = None) -> bool:
        """
        Tests API connection across ALL dedicated symbol channels simultaneously.
        Sends test ping to every symbol's channel in parallel and waits for all to respond.
        """
        cfg = get_gemini_config()
        resolved_model = model_name or cfg["primary_model"]
        cls.initialize(symbols, model_name=resolved_model)
        if not cls._agents:
            raise RuntimeError("FAIL-FAST: No symbols provided for Gemini dedicated channels.")

        async def _ping_single(sym: str, agent: GeminiApiAgent):
            prompt = f'{{"action": "PING", "symbol": "{sym}"}}'
            sys_inst = f'Reply with JSON: {{"status": "READY", "symbol": "{sym}"}}'
            start_t = time.perf_counter()
            resp = await agent.send_prompt_async(user_prompt=prompt, system_instruction=sys_inst)
            elapsed = (time.perf_counter() - start_t) * 1000
            logger.info(f"[DedicatedGeminiManager] {sym} ping verified in {elapsed:.0f}ms: {resp}")
            return sym, resp, elapsed

        async def _gather_pings():
            coroutines = [
                _ping_single(sym, cls.get_agent(sym))
                for sym in symbols
            ]
            return await asyncio.gather(*coroutines, return_exceptions=False)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, _gather_pings())
                    results = future.result(timeout=30)
            else:
                results = loop.run_until_complete(_gather_pings())
        except RuntimeError:
            results = asyncio.run(_gather_pings())
        except Exception as e:
            logger.exception(f"[DedicatedGeminiManager] AI Connection Test Failed: {e}")
            raise RuntimeError(f"FAIL-FAST: Google Gemini AI connection test failed: {e}") from e

        logger.info(
            f"[DedicatedGeminiManager] All {len(results)} dedicated AI channels verified and warmed up successfully: {[r[0] for r in results]}"
        )
        return True

    @classmethod
    def get_agent(cls, symbol: str) -> GeminiApiAgent:
        """Returns the dedicated GeminiApiAgent permanently bound to this symbol."""
        if symbol not in cls._agents:
            cls._agents[symbol] = GeminiApiAgent(
                api_key=cls._next_api_key(),
                model_name=cls._model_name
            )
        return cls._agents[symbol]

    @classmethod
    def get_quota_status(cls) -> Dict[str, Any]:
        """Returns current daily quota usage across primary and secondary models."""
        return quota_tracker.get_status()


import queue


class GeminiApiChannelPool:
    """
    Legacy Pool alias — delegates to DedicatedGeminiManager or provides pooled access.
    """

    def __init__(self, num_channels: int = 6, model_name: Optional[str] = None):
        if num_channels < 1:
            raise ValueError("FAIL-FAST: num_channels must be >= 1")
        self._pool: queue.Queue = queue.Queue()
        cfg = get_gemini_config()
        resolved_model = model_name or cfg["primary_model"]
        for i in range(num_channels):
            agent = GeminiApiAgent(model_name=resolved_model)
            self._pool.put(agent)
        self._num_channels = num_channels
        logger.info(f"[GeminiApiChannelPool] Initialized {num_channels} independent API channels.")

    def acquire(self) -> "GeminiApiAgent":
        """Blocks until a free channel is available, then returns it."""
        return self._pool.get(block=True)

    def release(self, channel: "GeminiApiAgent") -> None:
        """Returns the channel back to the pool."""
        self._pool.put(channel)

    @property
    def num_channels(self) -> int:
        return self._num_channels
