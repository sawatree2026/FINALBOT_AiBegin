"""AP Strategy Analyzer (Nemesis E-Book V.2 Section 3.2)."""
from typing import Dict, Any
from . import macd_divergence, price_action

def analyze_payload(fields: Dict[str, str], symbol: str) -> Dict[str, Any]:
    call_div = macd_divergence.evaluate(fields, "CALL")
    call_pa = price_action.evaluate(fields, "CALL")
    
    put_div = macd_divergence.evaluate(fields, "PUT")
    put_pa = price_action.evaluate(fields, "PUT")
    
    action = "WAIT"
    confidence = 0.0
    
    if call_div and call_pa:
        action = "CALL"
        confidence = 80.0
    elif put_div and put_pa:
        action = "PUT"
        confidence = 80.0
        
    return {
        "symbol": symbol,
        "action": action,
        "confidence_score": confidence,
        "engine_used": "STRATEGY_AP",
        "conditions_met": action != "WAIT",
        "details": {
            "divergence": call_div or put_div,
            "price_action": call_pa or put_pa,
        }
    }
