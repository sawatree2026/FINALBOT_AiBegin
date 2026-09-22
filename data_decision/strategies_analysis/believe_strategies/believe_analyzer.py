"""Disk-backed Believe strategy analyzer.

The analyzer reads the immutable evaluation payload itself.  It never receives
an in-memory payload from Part 2.
"""

from typing import Any, Dict, Optional

from . import (
    ap,
    bollinger_band,
    divergence,
    macd,
    moving_average,
    ns,
    price_action,
    rsi,
    stochastic,
    support_resistance_grid,
)

def _read_fields(payload_path: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    with open(payload_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip().strip("'\"")
    return fields


def _direction(value: Any) -> Optional[str]:
    text = str(value or "").upper()
    if text in {"UP", "UPTREND", "BULLISH", "CALL", "BUY", "LONG"}:
        return "CALL"
    if text in {"DOWN", "DOWNTREND", "BEARISH", "PUT", "SELL", "SHORT"}:
        return "PUT"
    return None


def _bool(value: Any) -> Optional[bool]:
    text = str(value or "").strip().upper()
    if text in {"TRUE", "1", "YES", "Y", "PASS", "PASSED"}:
        return True
    if text in {"FALSE", "0", "NO", "N", "FAIL", "FAILED"}:
        return False
    return None


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None


def _is_core_bollinger(fields: Dict[str, str], action: str) -> bool:
    return bollinger_band.evaluate(fields, action)


def _is_core_stochastic(fields: Dict[str, str], action: str) -> bool:
    return stochastic.evaluate(fields, action)


def _is_core_moving_average(fields: Dict[str, str], action: str) -> bool:
    return moving_average.evaluate(fields, action)


def _matches_action(value: Any, action: str) -> bool:
    direction = _direction(value)
    return direction == action


def _secondary_conditions(fields: Dict[str, str], action: str) -> Dict[str, bool]:
    """Evaluate documentary confirmations without replacing Believe's core."""
    return {
        "price_action": price_action.evaluate(fields, action),
        "grid_and_sr_clear": support_resistance_grid.evaluate(fields, action),
        "divergence_aligned": divergence.evaluate(fields, action),
        "macd_aligned": macd.evaluate(fields, action),
        "rsi_safe": rsi.evaluate(fields, action),
        "ap_aligned": ap.evaluate(fields, action),
        "ns_aligned": ns.evaluate(fields, action),
    }


def analyze_payload_file(symbol: str, payload_path: str) -> Dict[str, Any]:
    """Evaluate the complete disk-backed Believe rule set."""
    fields = _read_fields(payload_path)
    s30 = _direction(fields.get("s30_bias") or fields.get("s30_direction"))
    m1 = _direction(fields.get("m1_bias") or fields.get("m1_direction"))
    m5 = _direction(fields.get("m5_bias") or fields.get("m5_direction"))
    believe = _direction(fields.get("believe_direction"))
    candidate = believe or s30
    directions_aligned = (
        candidate in {"CALL", "PUT"}
        and s30 == candidate
        and m1 == candidate
        and m5 == candidate
    )
    core = {
        "bollinger_band": _is_core_bollinger(fields, candidate)
        if candidate in {"CALL", "PUT"}
        else False,
        "stochastic": _is_core_stochastic(fields, candidate)
        if candidate in {"CALL", "PUT"}
        else False,
        "moving_average": _is_core_moving_average(fields, candidate)
        if candidate in {"CALL", "PUT"}
        else False,
    }
    secondary = (
        _secondary_conditions(fields, candidate)
        if candidate in {"CALL", "PUT"}
        else {
            "price_action": False,
            "grid_and_sr_clear": False,
            "divergence_aligned": False,
            "macd_aligned": False,
            "rsi_safe": False,
            "ap_aligned": False,
            "ns_aligned": False,
        }
    )
    filters = {
        "grid_block": _bool(fields.get("believe_risk_grid_block")) is True,
        "gray_candle": _bool(fields.get("believe_risk_gray_candle")) is True,
        "trap": str(fields.get("believe_risk_trap_alert", "")).upper()
        not in {"", "NONE", "FALSE", "NO"},
        "room_to_run": _bool(fields.get("believe_risk_room_to_run_clear")),
    }
    filters_passed = not any(
        (filters["grid_block"], filters["gray_candle"], filters["trap"])
    ) and filters["room_to_run"] is not False
    action = (
        candidate
        if (
            directions_aligned
            and all(core.values())
            and all(secondary.values())
            and filters_passed
        )
        else "WAIT"
    )
    confidence = (
        {"HIGH": 85.0, "MEDIUM": 70.0}.get(
            str(fields.get("believe_confidence", "")).upper(), 60.0
        )
        if action != "WAIT"
        else 0.0
    )
    failed = [
        name for name, passed in core.items() if not passed
    ]
    failed.extend(
        name for name, passed in secondary.items() if not passed
    )
    if not directions_aligned:
        failed.append("timeframe_alignment")
    if not filters_passed:
        failed.append("risk_filters")

    return {
        "ID": fields.get("id") or payload_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].rsplit(".", 1)[0],
        "symbol": symbol,
        "action": action,
        "expiry_minutes": 5,
        "confidence_score": confidence,
        "engine_used": "STRATEGY_BELIEVE",
        "believe_status": fields.get("believe_status", "watch"),
        "believe_direction": believe or "WAIT",
        "s30_direction": s30 or "UNKNOWN",
        "m1_direction": m1 or "UNKNOWN",
        "m5_direction": m5 or "UNKNOWN",
        "m1_bias": fields.get("m1_bias", ""),
        "m5_bias": fields.get("m5_bias", ""),
        "m5_regime": fields.get("m5_trend_type") or fields.get("m5_regime", ""),
        "m5_adx": _number(fields.get("m5_adx")),
        "risk_level": fields.get("dl_risk_level") or fields.get("risk_level", ""),
        "data_quality": fields.get("m5_quality") or fields.get("data_quality", ""),
        "extreme_believe_active": str(
            fields.get("extreme_believe_active", "false")
        ).lower() == "true",
        "core_conditions": core,
        "secondary_conditions": secondary,
        "risk_filters": filters,
        "conditions_met": action != "WAIT",
        "failed_conditions": failed,
        "reason_th": (
            f"Believe core confirmed: Bollinger Band + Stochastic + Moving Average; "
            f"S30/M1/M5 aligned ({action})"
            if action != "WAIT"
            else "WAIT: Believe requires BB, Stochastic reversal/cross, moving-average confirmation, "
            "aligned S30/M1/M5, and clear risk filters"
        ),
    }
