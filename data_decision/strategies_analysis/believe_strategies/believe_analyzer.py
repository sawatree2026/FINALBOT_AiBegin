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
    if len(lines) != 99:
        raise ValueError(
            f"FAIL-FAST: Believe payload must contain exactly 99 lines, got {len(lines)}"
        )
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(
                f"FAIL-FAST: Malformed Believe payload line {line_number}: {raw_line!r}"
            )
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        if not normalized_key:
            raise ValueError(f"FAIL-FAST: Empty Believe payload key on line {line_number}")
        if normalized_key in fields:
            raise ValueError(f"FAIL-FAST: Duplicate Believe payload field: {normalized_key}")
        fields[normalized_key] = value.strip().strip("'\"")
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
    text = str(value or "").strip().upper()
    if text in {"TRUE", "1", "YES", "Y", "PASS", "PASSED"}:
        return True
    if text in {"FALSE", "0", "NO", "N", "FAIL", "FAILED"}:
        return False
    raise ValueError(f"Invalid boolean Believe payload value: {value!r}")


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric Believe payload value: {value!r}") from exc


def _require_fields(fields: Dict[str, str]) -> None:
    required = (
        "id", "s30_bias", "m1_bias", "m5_bias", "believe_direction",
        "believe_bb_percent_b", "believe_bb_touch",
        "believe_sto_k", "believe_sto_d", "believe_sto_zone",
        "believe_sto_cross", "believe_sto_hook_confirmed",
        "believe_sto_cross_50", "believe_risk_sto_tangled",
        "believe_ma_cross", "believe_ma_cross_confirmed",
        "believe_risk_grid_block", "believe_risk_gray_candle",
        "believe_risk_trap_alert", "believe_risk_room_to_run_clear",
        "m5_pa_pattern", "m5_pa_last_candle_bias",
        "m5_pa_sr_interaction", "m5_pa_divergence_alert",
        "s30_macd", "s30_macd_signal", "s30_macd_histogram", "s30_rsi",
        "m1_macd", "m1_macd_signal", "m1_macd_histogram",
        "m1_divergence_type", "m1_divergence_peak_count",
        "m1_adx",
        "ap_signal", "ns_signal", "believe_confidence",
        "believe_status", "m5_trend_type", "dl_risk_level",
        "extreme_believe_active",
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
    s30 = _required_direction(fields, "s30_bias")
    m1 = _required_direction(fields, "m1_bias")
    m5 = _required_direction(fields, "m5_bias")
    believe = _required_direction(fields, "believe_direction")
    # WAIT is a valid canonical strategy result; it must never be replaced
    # with a direction inferred from another field.
    candidate = believe if believe in {"CALL", "PUT"} else "WAIT"
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
        "grid_block": _bool(fields["believe_risk_grid_block"]) is True,
        "gray_candle": _bool(fields["believe_risk_gray_candle"]) is True,
        "stoch_tangled": _bool(fields["believe_risk_sto_tangled"]) is True,
        "trap": str(fields["believe_risk_trap_alert"]).upper()
        not in {"", "NONE", "FALSE", "NO"},
        "room_to_run": _bool(fields["believe_risk_room_to_run_clear"]),
    }
    filters_passed = not any(
        (filters["grid_block"], filters["gray_candle"], filters["stoch_tangled"], filters["trap"])
    ) and filters["room_to_run"] is not False
    # AP/NS, MACD, RSI, divergence, and price action are confirmations and
    # diagnostics; Believe's entry contract is BB + STO + MA plus risk filters.
    action = (
        candidate
        if (
            directions_aligned
            and all(core.values())
            and secondary["divergence_aligned"]
            and secondary["macd_aligned"]
            and filters_passed
        )
        else "WAIT"
    )
    confidence = (
        {"HIGH": 85.0, "MEDIUM": 70.0}.get(
            str(fields["believe_confidence"]).upper(), 60.0
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
        "ID": fields["id"] if "id" in fields and fields["id"].strip() else payload_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].rsplit(".", 1)[0],
        "symbol": symbol,
        "action": action,
        "expiry_minutes": 5,
        "confidence_score": confidence,
        "engine_used": "STRATEGY_BELIEVE",
        "believe_status": fields["believe_status"],
        "believe_direction": believe or "WAIT",
        "s30_direction": s30 or "UNKNOWN",
        "m1_direction": m1 or "UNKNOWN",
        "m5_direction": m5 or "UNKNOWN",
        "m1_bias": fields["m1_bias"],
        "m5_bias": fields["m5_bias"],
        "m5_regime": fields["m5_trend_type"],
        "m1_adx": _number(fields.get("m1_adx", 25.0)),
        "risk_level": fields["dl_risk_level"],
        "data_quality": fields.get("m5_quality") or fields.get("dl_quality_score", "HIGH"),
        "extreme_believe_active": _bool(fields["extreme_believe_active"]),
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
