"""U-Turn Strategy Analyzer (Nemesis E-Book V.2 Section 3.4)."""
from typing import Dict, Any
from . import stochastic_boundary, support_resistance

def analyze_payload(fields: Dict[str, str], symbol: str) -> Dict[str, Any]:
    call_sto = stochastic_boundary.evaluate(fields, "CALL")
    call_sr = support_resistance.evaluate(fields, "CALL")
    
    put_sto = stochastic_boundary.evaluate(fields, "PUT")
    put_sr = support_resistance.evaluate(fields, "PUT")
    
    action = "WAIT"
    confidence = 0.0
    
    if call_sto and call_sr:
        action = "CALL"
        confidence = 75.0
    elif put_sto and put_sr:
        action = "PUT"
        confidence = 75.0
        
    return {
        "symbol": symbol,
        "action": action,
        "confidence_score": confidence,
        "engine_used": "STRATEGY_UTURN",
        "conditions_met": action != "WAIT",
        "details": {
            "sto_boundary": call_sto or put_sto,
            "sr_bounce": call_sr or put_sr,
        }
    }
