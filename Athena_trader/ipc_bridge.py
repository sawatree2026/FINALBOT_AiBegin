import os
import json
import time
from typing import Dict, Any, Optional

class AthenaIPCBridge:
    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.signal_dir = os.path.join(base_dir, "signals")
        os.makedirs(self.signal_dir, exist_ok=True)
        
        self.feed_file = os.path.join(self.signal_dir, "market_feed.json")
        self.command_file = os.path.join(self.signal_dir, "order_command.json")
        self.history_file = os.path.join(self.signal_dir, "trade_history.json")

    def publish_market_feed(self, feed_data: Dict[str, Any]):
        temp_file = self.feed_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(feed_data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, self.feed_file)

    def read_market_feed(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.feed_file):
            return None
        try:
            with open(self.feed_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def publish_order_command(self, command: Dict[str, Any]):
        temp_file = self.command_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(command, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, self.command_file)

    def read_order_command(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.command_file):
            return None
        try:
            with open(self.command_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def log_trade(self, record: Dict[str, Any]):
        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []
                
        history.append(record)
        temp_file = self.history_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, self.history_file)
