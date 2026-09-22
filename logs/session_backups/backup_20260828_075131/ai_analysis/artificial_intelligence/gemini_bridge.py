"""
Gemini API Transport Driver for Part 3
=======================================
Pure transport layer: sends prompt → returns raw text response.
Primary model  : gemini-3.5-flash-lite
Fallback model : gemini-3.1-flash-lite
Supports both synchronous (send_prompt) and asynchronous (send_prompt_async) dispatch.
"""

import os
import time
import asyncio
import concurrent.futures
import logging
from typing import Optional, Dict, List

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

PRIMARY_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.1-flash-lite"

_FALLBACK_TRIGGERS = [
    "404", "not_found", "not found",
    "503", "high demand", "unavailable",
    "resource_exhausted", "429", "rate"
]


class GeminiApiAgent:
    """
    Pure Transport Driver for Google Gemini API.
    Responsible ONLY for sending prompt text and returning raw text response.
    Primary: gemini-3.5-flash-lite | Fallback: gemini-3.1-flash-lite
    """

    def __init__(self, api_key: Optional[str] = None, model_name: str = PRIMARY_MODEL):
        if api_key is not None and not isinstance(api_key, str):
            raise TypeError(f"FAIL-FAST: api_key must be a string, got {type(api_key)}")
        if not isinstance(model_name, str):
            raise TypeError(f"FAIL-FAST: model_name must be a string, got {type(model_name)}")

        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("FAIL-FAST: GEMINI_API_KEY is not set in environment or .env file.")

        self.model_name = model_name
        self._models_to_try = self._build_model_list(model_name)

        try:
            self.client = genai.Client(api_key=self.api_key)
            logger.info(
                f"[GeminiApiAgent] Initialized | Primary: {self._models_to_try[0]} "
                f"| Fallback: {self._models_to_try[1] if len(self._models_to_try) > 1 else 'None'}"
            )
        except Exception as e:
            logger.exception("[GeminiApiAgent] Could not initialize Google GenAI client.")
            raise RuntimeError(f"FAIL-FAST: Google GenAI client initialization failed: {e}") from e

    @staticmethod
    def _build_model_list(primary: str) -> list:
        """Returns ordered [primary, fallback] list with no duplicates."""
        ordered = [primary]
        if FALLBACK_MODEL != primary:
            ordered.append(FALLBACK_MODEL)
        return ordered

    def send_prompt(self, user_prompt: str, system_instruction: str = "") -> str:
        """
        Synchronous dispatch to Gemini API.
        Tries primary model first, then fallback on rate-limit / not-found errors.
        """
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("FAIL-FAST: user_prompt must be a non-empty string.")

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2
        )
        if system_instruction:
            config.system_instruction = system_instruction

        last_err = None
        for model in self._models_to_try:
            try:
                logger.info(f"[GeminiApiAgent] Dispatching to model: {model}")
                response = self.client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config
                )
                txt = (response.text or "").strip()
                if txt:
                    logger.info(f"[GeminiApiAgent] Response received from: {model}")
                    return txt
                logger.warning(f"[GeminiApiAgent] Empty response from {model}, trying next...")
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if any(t in err_str for t in _FALLBACK_TRIGGERS):
                    logger.warning(
                        f"[GeminiApiAgent] {model} hit rate-limit/fallback trigger ({e}), switching..."
                    )
                    continue
                logger.exception(f"[GeminiApiAgent] Non-recoverable error on {model}: {e}")
                raise RuntimeError(f"FAIL-FAST: Gemini API call failed: {e}") from e

        if last_err is not None:
            logger.error(
                f"[GeminiApiAgent] All models exhausted. Last error: {last_err}",
                exc_info=(type(last_err), last_err, last_err.__traceback__)
            )
        else:
            logger.error("[GeminiApiAgent] All models exhausted with no captured error.")
        raise RuntimeError(
            f"FAIL-FAST: Gemini API failed on all models [{', '.join(self._models_to_try)}]: {last_err}"
        ) from last_err

    async def send_prompt_async(self, user_prompt: str, system_instruction: str = "") -> str:
        """
        Asynchronous dispatch — used by asyncio.gather() for N-symbol concurrent calls.
        Runs blocking send_prompt() in a thread pool executor to avoid blocking the event loop.
        """
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("FAIL-FAST: user_prompt must be a non-empty string.")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.send_prompt, user_prompt, system_instruction)


class DedicatedGeminiManager:
    """
    Dedicated 1:1 Gemini API Channels for each trading symbol.
    Provides persistent, warm TCP/SSL connections permanently bound to each pair.
    """
    _agents: Dict[str, GeminiApiAgent] = {}
    _model_name: str = PRIMARY_MODEL

    @classmethod
    def initialize(cls, symbols: List[str], model_name: str = PRIMARY_MODEL) -> None:
        """Pre-warms and binds a dedicated channel for each symbol at startup."""
        cls._model_name = model_name
        for sym in symbols:
            if sym not in cls._agents:
                cls._agents[sym] = GeminiApiAgent(model_name=model_name)
        logger.info(
            f"[DedicatedGeminiManager] Initialized {len(cls._agents)} dedicated channels for: {list(cls._agents.keys())}"
        )

    @classmethod
    def test_connection(cls, symbols: List[str], model_name: str = PRIMARY_MODEL) -> bool:
        """
        Tests API connection across ALL dedicated symbol channels simultaneously.
        Sends test ping to every symbol's channel in parallel and waits for all to respond.
        """
        cls.initialize(symbols, model_name=model_name)
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
            cls._agents[symbol] = GeminiApiAgent(model_name=cls._model_name)
        return cls._agents[symbol]


import queue


class GeminiApiChannelPool:
    """
    Legacy Pool alias — delegates to DedicatedGeminiManager or provides pooled access.
    """

    def __init__(self, num_channels: int = 6, model_name: str = PRIMARY_MODEL):
        if num_channels < 1:
            raise ValueError("FAIL-FAST: num_channels must be >= 1")
        self._pool: queue.Queue = queue.Queue()
        for i in range(num_channels):
            agent = GeminiApiAgent(model_name=model_name)
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

