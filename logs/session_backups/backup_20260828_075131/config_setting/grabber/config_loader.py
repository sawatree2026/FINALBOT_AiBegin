"""
Settings loader — single source of truth for runtime config.

Reads config/settings.json once and exposes helpers for the rest
of the codebase. Used by IQOptionAdapter, BotRunner, launcher, etc.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_CACHE: Optional[Dict[str, Any]] = None


def _find_settings_file() -> Path:
    """Locate config/settings.json regardless of working directory."""
    here = Path(__file__).resolve().parent  # config_setting directory
    candidates = [
        here / "settings.json",
        Path.cwd() / "config" / "settings.json",
        Path.cwd() / "config_setting" / "settings.json",
        Path("config/settings.json"),
        Path("config_setting/settings.json"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError("config/settings.json not found")


def load_settings(reload: bool = False) -> Dict[str, Any]:
    """Load (and cache) settings.json. Set reload=True to re-read from disk."""
    global _CACHE
    if _CACHE is None or reload:
        path = _find_settings_file()
        with open(path, "r", encoding="utf-8") as f:
            _CACHE = json.load(f)
    return _CACHE


#  Convenience getters 

def get_account() -> Dict[str, Any]:
    return load_settings().get("account", {})


def get_iq_credentials() -> tuple[str, str]:
    """
    Return (email, password) for IQ Option.

    Source: config/settings.json -> account.iq_email / account.iq_password
    (single source of truth — no env vars, no .env file)

    The placeholder strings shipped with the template are treated as empty.
    """
    acc = get_account()
    email = str(acc.get("iq_email", "")).strip()
    password = str(acc.get("iq_password", "")).strip()

    # Reject Thai placeholder text from the template
    if email.startswith("ใส่") or password.startswith("ใส่"):
        return "", ""
    return email, password


def get_account_type() -> str:
    return get_account().get("account_type", "PRACTICE")


def get_trading_mode() -> str:
    return str(get_account().get("trading_mode", "SIGNALBOT")).strip().upper()


def get_capital() -> float:
    return float(load_settings().get("capital", {}).get("starting_balance", 2000.0))


def get_limits() -> Dict[str, Any]:
    return load_settings().get("limits", {})


def get_execution_gate() -> Dict[str, Any]:
    return load_settings().get("execution_gate", {})


def get_session() -> Dict[str, Any]:
    return load_settings().get("session", {})


def get_symbols() -> list[str]:
    symbols = load_settings(reload=True).get("symbols")
    if not symbols or not isinstance(symbols, list):
        raise ValueError("FAIL-FAST: Missing or empty 'symbols' array in config_setting/settings.json")
    return list(symbols)


def load_datafeed_settings() -> Dict[str, Any]:
    """Load datafeed configuration from settings"""
    return load_settings().get("data_feed", {})




def get_csv_writer_config() -> Dict[str, Any]:
    """Get CSV writer configuration"""
    settings = load_settings()
    return settings.get("data_feed", {}).get("csv_writer", settings.get("csv_writer", {}))


def get_csv_manager_config() -> Dict[str, Any]:
    """Get CSV manager configuration"""
    settings = load_settings()
    return settings.get("data_feed", {}).get("csv_manager", settings.get("csv_manager", {}))


def get_csv_queue_config() -> Dict[str, Any]:
    """Get CSV queue configuration"""
    settings = load_settings()
    return settings.get("data_feed", {}).get("csv_queue", settings.get("csv_queue", {}))


def get_time_sync_manager_config() -> Dict[str, Any]:
    """Get time sync manager configuration"""
    settings = load_settings()
    return settings.get("time_sync_manager", {})


