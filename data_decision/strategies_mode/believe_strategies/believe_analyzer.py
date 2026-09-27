"""Disk-backed Believe strategy analyzer.

The analyzer reads the immutable evaluation payload itself.  It never receives
an in-memory payload from Part 2.
"""

from typing import Any, Dict, Optional

from . import (
    ap,
    bollinger_percent as bollinger_band,
    divergence,
    macd,
    moving_average,
    ns,
    price_action,
    rsi,
    stochastic,
    grid,
    support_resistance,
)

def _read_fields(payload_path: str) -> Dict[str, str]:
    if not isinstance(payload_path, str) or not payload_path.strip():
        raise ValueError("FAIL-FAST: Believe payload path must be a non-empty string")
    fields: Dict[str, str] = {}
    with open(payload_path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    if len(lines) < 10:
        raise ValueError(
            f"FAIL-FAST: Believe payload must contain at least 10 lines, got {len(lines)}"
        )
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        if not normalized_key:
            continue
        fields[normalized_key] = value.strip().strip("'\"")

    # Alias compatibility for single-pass 78-line payload
    aliases = {
        "bb_percent_b": "believe_bb_percent_b",
        "bb_touch": "believe_bb_touch",
        "bb_percent_touch": "believe_bb_touch",
        "sto_k": "believe_sto_k",
        "sto_d": "believe_sto_d",
        "sto_zone": "believe_sto_zone",
        "sto_cross": "believe_sto_cross",
        "sto_cross_50": "believe_sto_cross_50",
        "sto_hook_confirmed": "believe_sto_hook_confirmed",
        "sto_tangled": "believe_risk_sto_tangled",
        "ma_fast": "believe_ma_fast",
        "ma_slow": "believe_ma_slow",
        "ma_cross": "believe_ma_cross",
        "ma_cross_confirmed": "believe_ma_cross_confirmed",
        "grid_block_ahead": "believe_risk_grid_block",
        "gray_candle_present": "believe_risk_gray_candle",
        "macd": "s30_macd",
        "macd_signal": "s30_macd_signal",
        "macd_histogram": "s30_macd_histogram",
        "rsi": "s30_rsi",
        "divergence_alert": "m5_pa_divergence_alert",
        "pa_pattern": "m5_pa_pattern",
        "sr_type": "m5_pa_sr_interaction",
    }
    for src, dst in aliases.items():
        if src in fields and dst not in fields:
            fields[dst] = fields[src]

    # Defaults for required fields if missing
    defaults = {
        "id": payload_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].rsplit(".", 1)[0],
        "s30_bias": fields.get("bias", "WAIT"),
        "m1_bias": "WAIT",
        "m5_bias": "WAIT",
        "ap_signal": "NEUTRAL",
        "ns_signal": "NEUTRAL",
        "m5_pa_divergence_alert": fields.get("divergence_alert", "NONE"),
        "m5_pa_pattern": fields.get("pa_pattern", "NONE"),
        "m5_pa_last_candle_bias": fields.get("bias", "NEUTRAL"),
        "m5_pa_sr_interaction": fields.get("sr_type", "NONE"),
        "believe_direction": (
            "CALL" if fields.get("believe_ma_cross") in {"UP", "BULLISH", "CALL", "GOLDEN_CROSS"}
            else "PUT" if fields.get("believe_ma_cross") in {"DOWN", "BEARISH", "PUT", "DEATH_CROSS"}
            else "WAIT"
        ),
        "believe_risk_room_to_run_clear": str(fields.get("believe_risk_grid_block", "FALSE").upper() not in {"TRUE", "1", "YES"}),
    }
    for k, v in defaults.items():
        if k not in fields or not fields[k].strip():
            fields[k] = v

    return fields


def _direction(value: Any) -> Optional[str]:
    text = str(value).strip().upper()
    if text in {"UP", "UPTREND", "BULLISH", "CALL", "BUY", "LONG"}:
        return "CALL"
    if text in {"DOWN", "DOWNTREND", "BEARISH", "PUT", "SELL", "SHORT"}:
        return "PUT"
    if text in {"WAIT", "NONE", "NEUTRAL"}:
        return "WAIT"
    return None


def _required_direction(fields: Dict[str, str], key: str) -> str:
    direction = _direction(fields[key])
    if direction is None:
        raise ValueError(f"Invalid Believe payload direction for {key}: {fields[key]!r}")
    return direction


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().upper()
    if text in {"TRUE", "1", "YES", "Y", "PASS", "PASSED"}:
        return True
    if text in {"FALSE", "0", "NO", "N", "FAIL", "FAILED", ""}:
        return False
    raise ValueError(f"Invalid boolean Believe payload value: {value!r}")


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric Believe payload value: {value!r}") from exc


def _require_fields(fields: Dict[str, str]) -> None:
    required = (
        "id", "s30_bias", "believe_direction",
        "believe_bb_percent_b", "believe_bb_touch",
        "believe_sto_k", "believe_sto_d", "believe_sto_zone",
        "believe_sto_cross", "believe_sto_hook_confirmed",
        "believe_ma_cross", "believe_ma_cross_confirmed",
        "believe_risk_grid_block",
    )
    missing = [key for key in required if key not in fields or not fields[key].strip()]
    if missing:
        raise ValueError(
            "Required Believe payload fields missing or empty: "
            + ", ".join(missing)
        )


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
        "grid_clear": grid.evaluate(fields, action),
        "support_resistance_clear": support_resistance.evaluate(fields, action),
        # Keep the legacy aggregate field for downstream consumers.
        "grid_and_sr_clear": (
            grid.evaluate(fields, action)
            and support_resistance.evaluate(fields, action)
        ),
        "divergence_aligned": divergence.evaluate(fields, action),
        "macd_aligned": macd.evaluate(fields, action),
        "rsi_safe": rsi.evaluate(fields, action),
        "ap_aligned": ap.evaluate(fields, action),
        "ns_aligned": ns.evaluate(fields, action),
    }


def analyze_payload_file(symbol: str, payload_path: str) -> Dict[str, Any]:
    """Evaluate the complete disk-backed Believe rule set."""
    fields = _read_fields(payload_path)
    _require_fields(fields)
    s30 = fields.get("s30_bias", "WAIT")
    believe = _required_direction(fields, "believe_direction")
    # WAIT is a valid canonical strategy result; it must never be replaced
    # with a direction inferred from another field.
    candidate = believe if believe in {"CALL", "PUT"} else "WAIT"
    directions_aligned = candidate in {"CALL", "PUT"}
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
            "grid_clear": False,
            "support_resistance_clear": False,
            "grid_and_sr_clear": False,
            "divergence_aligned": False,
            "macd_aligned": False,
            "rsi_safe": False,
            "ap_aligned": False,
            "ns_aligned": False,
        }
    )
    filters = {
        "grid_block": _bool(fields.get("believe_risk_grid_block", False)) is True,
        "gray_candle": _bool(fields.get("believe_risk_gray_candle", False)) is True,
        "stoch_tangled": _bool(fields.get("believe_risk_sto_tangled", False)) is True,
        "trap": str(fields.get("believe_risk_trap_alert", "NONE")).upper()
        not in {"", "NONE", "FALSE", "NO"},
        "room_to_run": _bool(fields.get("believe_risk_room_to_run_clear", True)),
    }
    filters_passed = not any(
        (filters["grid_block"], filters["gray_candle"], filters["stoch_tangled"], filters["trap"])
    ) and filters["room_to_run"] is not False

    # 1. Extreme Combination (Nemesis V.2 p.50-52)
    # Primary driver: Divergence + MACD 0-line alignment, then trigger with Believe (STO + MA)
    div_alert = str(fields.get("divergence_alert", "NONE")).upper()
    has_bullish_div = ("BULLISH" in div_alert or "STO_BULLISH" in div_alert or "RSI_BULLISH" in div_alert)
    has_bearish_div = ("BEARISH" in div_alert or "STO_BEARISH" in div_alert or "RSI_BEARISH" in div_alert)
    has_divergence = (has_bullish_div and candidate == "CALL") or (has_bearish_div and candidate == "PUT")

    macd_val = _number(fields.get("macd", fields.get("s30_macd", 0.0))) or 0.0
    macd_zero_aligned = (macd_val <= 0.0002 if candidate == "CALL" else macd_val >= -0.0002)

    is_extreme = (
        directions_aligned
        and filters_passed
        and has_divergence
        and macd_zero_aligned
        and core["stochastic"]
        and core["moving_average"]
    )

    # 2. Pure Believe (Nemesis V.2 p.37, 49)
    # Core: BB% 0/1 touch + STO 10/90 reversal + MA crossover + Risk Filters
    is_pure = (
        directions_aligned
        and filters_passed
        and all(core.values())
    )

    if is_extreme:
        action = candidate
        engine_used = "STRATEGY_BELIEVE_EXTREME"
        confidence = 88.0
        reason_th = f"Believe Extreme confirmed: Divergence ({div_alert}) + MACD 0-line + Believe trigger (MA/STO) ({action})"
    elif is_pure:
        action = candidate
        engine_used = "STRATEGY_BELIEVE_PURE"
        confidence = 75.0
        reason_th = f"Believe Pure confirmed: BB% touch (1/0) + STO 10/90 + MA EMA3/SMA6 cross ({action})"
    else:
        action = "WAIT"
        engine_used = "STRATEGY_BELIEVE"
        confidence = 0.0
        reason_th = "WAIT: Conditions not met for Believe Pure (BB 0/1 + STO 10/90 + MA) or Extreme (Divergence + MACD + Believe)"

    failed = [
        name for name, passed in core.items() if not passed
    ]
    if not is_extreme:
        if not has_divergence:
            failed.append("divergence_extreme")
        if not macd_zero_aligned:
            failed.append("macd_zero_line_extreme")
    if not directions_aligned:
        failed.append("timeframe_alignment")
    if not filters_passed:
        failed.append("risk_filters")

    return {
        "ID": fields.get("id") or payload_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].rsplit(".", 1)[0],
        "symbol": symbol,
        "action": action,
        "expiry_minutes": 3,
        "confidence_score": confidence,
        "engine_used": engine_used,
        "believe_status": fields.get("believe_status", "ACTIVE"),
        "believe_direction": believe or "WAIT",
        "s30_direction": s30 or "UNKNOWN",
        "m1_direction": fields.get("m1_bias", "UNKNOWN"),
        "m5_direction": fields.get("m5_bias", "UNKNOWN"),
        "m1_bias": fields.get("m1_bias", "UNKNOWN"),
        "m5_bias": fields.get("m5_bias", "UNKNOWN"),
        "m5_regime": fields.get("m5_trend_type", "UNKNOWN"),
        "m1_adx": _number(fields.get("m1_adx", 25.0)),
        "risk_level": fields.get("dl_risk_level", "LOW"),
        "data_quality": fields.get("m5_quality", "HIGH"),
        "extreme_believe_active": is_extreme,
        "pure_believe_active": is_pure,
        "core_conditions": core,
        "secondary_conditions": secondary,
        "risk_filters": filters,
        "conditions_met": action != "WAIT",
        "failed_conditions": failed,
        "reason_th": reason_th,
    }
