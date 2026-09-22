"""
Base Engine

Base class with common functionality for all engines.
"""

import time
import logging
import traceback
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import pandas as pd

from abc import ABC

from data_evaluate.exceptions import InvalidInputError, ComputationError


class BaseEngine(ABC):
    """
    Base class with common functionality for all engines.
    Provides timing, error handling, logging, and validation.
    """
    
    # Override these in subclasses
    ENGINE_NAME = "base_engine"
    ENGINE_VERSION = "1.0.0"
    TIER = 0
    MIN_CANDLES = 100
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._last_execution_time_ms: Optional[float] = None
    
    @property
    def engine_name(self) -> str:
        return self.ENGINE_NAME
    
    @property
    def engine_version(self) -> str:
        return self.ENGINE_VERSION
    
    @property
    def tier(self) -> int:
        return self.TIER
    
    def analyze(self, payload: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Standard analyze entry point. Wraps _analyze with safety.
        """
        start_time = time.time()
        
        try:
            if payload is None:
                raise InvalidInputError(f"[{self.ENGINE_NAME}] FAIL-FAST: payload cannot be None")

            # Validate input
            if hasattr(self, 'validate_input') and not self.validate_input(payload):
                raise InvalidInputError(f"[{self.ENGINE_NAME}] FAIL-FAST: validate_input failed for payload")
            
            # Run actual analysis
            try:
                result = self._analyze(payload, **kwargs)
            except Exception as e:
                raise ComputationError(f"[{self.ENGINE_NAME}] Computation failed: {e}") from e
            
            if not isinstance(result, dict):
                raise ComputationError(f"[{self.ENGINE_NAME}] FAIL-FAST: Output must be a dictionary")

            # Track timing
            self._last_execution_time_ms = (time.time() - start_time) * 1000
            
            return result
            
        except Exception as e:
            logging.exception(f"[{self.ENGINE_NAME}] Critical failure in analyze: {str(e)}")
            traceback.print_exc()
            raise
    
    def get_neutral_state(self) -> dict:
        return {}

    def _analyze(self, payload: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Override this in subclasses.
        Contains the actual analysis logic.
        """
        raise NotImplementedError("Subclasses must implement _analyze()")
    
    
    def to_engine_output(self, data: Dict[str, Any], 
                        confidence: int = 50) -> Dict[str, Any]:
        """Wrap data in standard EngineOutput format"""
        return {
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "timestamp": datetime.now(timezone.utc),
            "data": data,
            "confidence": confidence,
            "execution_time_ms": self._last_execution_time_ms,
        }
    
    @property
    def last_execution_time_ms(self) -> Optional[float]:
        return self._last_execution_time_ms
