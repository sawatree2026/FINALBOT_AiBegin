"""NS Strategy Analyzer (Nemesis E-Book V.2 Section 3.3)."""
from typing import Dict, Any
from . import macd_crossover, gray_candle_filter

def analyze_payload(fields: Dict[str, str], symbol: str) -> Dict[str, Any]:
    clear = gray_candle_filter.is_clear(fields)
    
    call_macd = macd_crossover.evaluate(fields, "CALL")
    put_macd = macd_crossover.evaluate(fields, "PUT")
    
    action = "WAIT"
    confidence = 0.0
    
    if clear:
        if call_macd:
            action = "CALL"
            confidence = 78.0
        elif put_macd:
            action = "PUT"
            confidence = 78.0
            
    return {
        "symbol": symbol,
        "action": action,
        "confidence_score": confidence,
        "engine_used": "STRATEGY_NS",
        "conditions_met": action != "WAIT",
        "details": {
            "gray_filter_clear": clear,
            "macd_crossover": call_macd or put_macd,
        }
    }
