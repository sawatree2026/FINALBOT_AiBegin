"""
Signal Throttle / Cooldown Manager

Prevents overtrading by enforcing cooldowns between signals of the same type.
"""

import time
from typing import Dict, Optional
from threading import Lock


class SignalThrottle:
    """
    Throttles signals to prevent overtrading and allow market confirmation.
    
    Features:
    - Cooldown per symbol + action (CALL/PUT)
    - Optional global cooldown across all symbols
    - Adaptive cooldown based on recent win/loss
    """
    
    def __init__(self, 
                 default_cooldown_seconds: int = 300,  # 5 minutes
                 global_cooldown_seconds: int = 60,    # 1 minute between any trades
                 adaptive: bool = True):
        self.default_cooldown = default_cooldown_seconds
        self.global_cooldown = global_cooldown_seconds
        self.adaptive = adaptive
        self._last_signal_time: Dict[str, float] = {}
        self._last_global_time: float = 0
        self._recent_results: Dict[str, list] = {}  # symbol_action -> list of bool (win/loss)
        self._lock = Lock()
    
    def allow(self, symbol: str, action: str) -> tuple[bool, str]:
        """
        Check if a signal is allowed.
        Returns (allowed, reason).
        """
        with self._lock:
            now = time.time()
            key = f"{symbol}_{action.upper()}"
            
            # Global cooldown check
            if now - self._last_global_time < self.global_cooldown:
                remaining = int(self.global_cooldown - (now - self._last_global_time))
                return False, f"Global cooldown: {remaining}s remaining"
            
            # Per-signature cooldown
            cooldown = self._get_cooldown(key)
            if key in self._last_signal_time:
                elapsed = now - self._last_signal_time[key]
                if elapsed < cooldown:
                    remaining = int(cooldown - elapsed)
                    return False, f"Signal cooldown for {key}: {remaining}s remaining"
            
            return True, "Allowed"
    
    def record_signal(self, symbol: str, action: str, result: Optional[bool] = None):
        """
        Record that a signal was executed (or just triggered).
        If result is provided, updates adaptive cooldown.
        """
        with self._lock:
            now = time.time()
            key = f"{symbol}_{action.upper()}"
            self._last_signal_time[key] = now
            self._last_global_time = now
            
            if result is not None and self.adaptive:
                if key not in self._recent_results:
                    self._recent_results[key] = []
                self._recent_results[key].append(result)
                # Keep last 10 results
                if len(self._recent_results[key]) > 10:
                    self._recent_results[key] = self._recent_results[key][-10:]
    
    def _get_cooldown(self, key: str) -> int:
        """Get adaptive cooldown based on recent performance."""
        if not self.adaptive or key not in self._recent_results:
            return self.default_cooldown
        
        results = self._recent_results[key]
        if not results:
            return self.default_cooldown
        
        win_rate = sum(results) / len(results)
        
        # Adaptive cooldown:
        # - High win rate (>60%) -> shorter cooldown (faster trading)
        # - Low win rate (<40%) -> longer cooldown (more cautious)
        if win_rate >= 0.60:
            return max(180, self.default_cooldown - 120)  # 3-5 min
        elif win_rate <= 0.40:
            return min(600, self.default_cooldown + 120)  # 5-10 min
        else:
            return self.default_cooldown
    
    def reset(self, symbol: Optional[str] = None, action: Optional[str] = None):
        """Reset cooldown for specific or all signals."""
        with self._lock:
            if symbol and action:
                key = f"{symbol}_{action.upper()}"
                self._last_signal_time.pop(key, None)
            else:
                self._last_signal_time.clear()
                self._last_global_time = 0
    
    def get_status(self) -> Dict:
        """Get current throttle status for monitoring."""
        with self._lock:
            now = time.time()
            status = {
                "global_cooldown_remaining": max(0, self.global_cooldown - (now - self._last_global_time)),
                "signal_cooldowns": {}
            }
            for key, last_time in self._last_signal_time.items():
                cooldown = self._get_cooldown(key)
                remaining = max(0, cooldown - (now - last_time))
                status["signal_cooldowns"][key] = remaining
            return status
