import json
import os
from dataclasses import dataclass
from typing import List

@dataclass
class AthenaConfig:
    iq_email: str
    iq_password: str
    account_type: str = "DEMO"
    stake_per_trade: float = 35.0
    min_payout: int = 84
    max_daily_loss: float = 500.0
    max_daily_profit: float = 1000.0
    default_symbols: List[str] = None

    @classmethod
    def load_from_settings(cls, settings_path: str = r"E:\FINALBOT_AiBegin\config_setting\settings.json") -> "AthenaConfig":
        if not os.path.exists(settings_path):
            raise FileNotFoundError(f"Configuration file not found: {settings_path}")
        
        with open(settings_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            
        acc = raw.get("account", {})
        return cls(
            iq_email=acc.get("iq_email", ""),
            iq_password=acc.get("iq_password", ""),
            account_type=acc.get("account_type", "DEMO"),
            stake_per_trade=float(acc.get("stake_per_trade", 35.0)),
            min_payout=int(raw.get("min_payout", 84)),
            max_daily_loss=float(acc.get("max_daily_loss", 500.0)),
            max_daily_profit=float(acc.get("max_daily_profit", 1000.0)),
            default_symbols=["EURUSD", "GBPUSD", "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC"]
        )
