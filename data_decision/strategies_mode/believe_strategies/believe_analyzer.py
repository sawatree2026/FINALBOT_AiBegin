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
        "bb_percent_touch": "believe_bb_touch",
        "bb_touch_low": "believe_bb_touch_low",
        "bb_touch_high": "believe_bb_touch_high",
        "sto_k": "believe_sto_k",
        "sto_d": "believe_sto_d",
        "sto_zone": "believe_sto_zone",
        "sto_cross": "believe_sto_cross",
        "sto_cross_50": "believe_sto_cross_50",
        "sto_cross_50_direction": "believe_sto_cross_50_direction",
        "sto_hook_confirmed": "believe_sto_hook_confirmed",
        "sto_touch_low": "believe_sto_touch_low",
        "sto_touch_high": "believe_sto_touch_high",
        "sr_block_call": "believe_sr_block_call",
        "sr_block_put": "believe_sr_block_put",
        "prev_candle_bad": "believe_risk_prev_candle_bad",
        "sto_tangled": "believe_risk_sto_tangled",
        "ma_fast": "believe_ma_fast",
        "ma_slow": "believe_ma_slow",
        "ma_cross": "believe_ma_cross",
        "ma_cross_confirmed": "believe_ma_cross_confirmed",
        "grid_block_ahead": "believe_risk_grid_block",
        "gray_candle_present": "believe_risk_gray_candle",
    }
    for src, dst in aliases.items():
        if src in fields and dst not in fields:
            fields[dst] = fields[src]

    # Defaults for required fields if missing
    defaults = {
        "id": payload_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].rsplit(".", 1)[0],
        "s30_bias": fields.get("bias", "WAIT"),
        "m1_bias": fields.get("bias", "WAIT"),
        "m5_bias": fields.get("bias", "WAIT"),
        "believe_direction": (
            "CALL" if fields.get("believe_ma_cross") in {"UP", "BULLISH", "CALL", "GOLDEN_CROSS"}
            else "PUT" if fields.get("believe_ma_cross") in {"DOWN", "BEARISH", "PUT", "DEATH_CROSS"}
            else "WAIT"
        ),
        # FIX 2026-09-26 (Audit F-3): ลบค่าประดิษฐ์ที่ปกปิดข้อมูลขาดทั้งหมด
        # (believe_confidence="HIGH", dl_risk_level="LOW", m5_trend_type="TRENDING", s30_rsi="50.0" ฯลฯ)
        # ฟิลด์เหล่านี้ถูก Part 2 emit ลง payload 99 บรรทัดอยู่แล้ว -> ย้ายไปบังคับใน required แทน (fail-fast)
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
        "id", "s30_bias", "believe_direction",
        "believe_bb_percent_b", "believe_bb_touch",
        "believe_sto_k", "believe_sto_d", "believe_sto_zone",
        "believe_sto_cross_50_direction", "believe_sto_hook_confirmed",
        "believe_sto_touch_low", "believe_sto_touch_high",
        "believe_risk_sto_tangled",
        "believe_ma_cross", "believe_ma_cross_confirmed",
        "believe_risk_grid_block", "is_doji", "is_gray_candle",
        "believe_sr_block_call", "believe_sr_block_put",
        "believe_risk_prev_candle_bad", "gray_candle_present",
        "doji_present", "macd", "divergence_alert",
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
        # N-4 (p.54) / N-5 (น.10): confirmation ตามตำรา — ไม่บังคับเข้า
        "fractal_aligned": text(fields, "believe_fractal_hint") == action,
        "follow_aligned": text(fields, "believe_follow_candle_dir") == action,
    }


def analyze_payload_file(symbol: str, payload_path: str) -> Dict[str, Any]:
    """Evaluate Believe from the active single-pass S30/M1 disk payload."""
    fields = _read_fields(payload_path)
    _require_fields(fields)
    s30 = fields.get("s30_bias", "UNKNOWN")
    believe = _required_direction(fields, "believe_direction")
    candidate = believe if believe in {"CALL", "PUT"} else "WAIT"
    # BOSS COMMAND: ยึดทิศทางตามกลยุทธ์ Believe (BB% + STO + MA) ไม่ใช้เทรนด์ M15/EMA20 ขวางการกลับตัว
    directions_aligned = candidate in {"CALL", "PUT"}
    # BOSS COMMAND: เอาเงื่อนไขอื่นออกทั้งหมด ให้เหลือเพียง 1 เดียวคือ MA 3 ตัด 6 ออกออเดอร์ทันที
    core = {
        "bollinger_band": True,
        "stochastic": True,
        "moving_average": _is_core_moving_average(fields, candidate)
        if candidate in {"CALL", "PUT"}
        else False,
    }
    sr_block = (
        _bool(fields["believe_sr_block_call"]) if candidate == "CALL"
        else _bool(fields["believe_sr_block_put"]) if candidate == "PUT"
        else False
    )
    filters = {
        # BOSS COMMAND: ตัดเส้นกริด, แนวรับต้าน, และ Safety Filter ออกทั้งหมดตามคำสั่งบอส
        "grid_block": False,
        "gray_candle": False,
        "doji_window_15m": False,
        "gray_window_15m": False,
        "prev_candle_bad": False,
        "sr_block_ahead": False,
        "stoch_tangled": False,
    }
    filters_passed = not any(
        filters.values()
    )
    action = (
        candidate
        if directions_aligned and all(core.values()) and filters_passed
        else "WAIT"
    )
    divergence_alert = fields["divergence_alert"].upper()
    divergence_aligned = (
        ("BULLISH" in divergence_alert and action == "CALL")
        or ("BEARISH" in divergence_alert and action == "PUT")
    )
    macd_value = _number(fields["macd"])
    macd_zero_aligned = (
        macd_value is not None
        and (
            (action == "CALL" and macd_value <= 0.0002)
            or (action == "PUT" and macd_value >= -0.0002)
        )
    )

    # Nemesis V.2 Believe Pure / Extreme Branching (E-Book p.37, p.50)
    is_extreme = action != "WAIT" and divergence_aligned and macd_zero_aligned
    if is_extreme:
        confidence = 88.0
        engine_used = "STRATEGY_BELIEVE_EXTREME"
        extreme_active = True
        reason_th = f"Believe Extreme (Divergence+MACD0+Believe) confirmed on S30 ({action})"
    elif action != "WAIT":
        confidence = 75.0
        engine_used = "STRATEGY_BELIEVE_PURE"
        extreme_active = False
        reason_th = f"Believe Pure confirmed on S30 with M1 grid/SR safety filters ({action})"
    else:
        confidence = 0.0
        engine_used = "STRATEGY_BELIEVE"
        extreme_active = False
        reason_th = "WAIT: Believe requires S30 BB, STO hook and 50-cross, MA confirmation, and safety filters"

    failed = [name for name, passed in core.items() if not passed]
    if not directions_aligned:
        failed.append("s30_direction")
    if not filters_passed:
        failed.append("risk_filters")

    return {
        "ID": fields["id"],
        "symbol": symbol,
        "action": action,
        "expiry_minutes": 3,
        "confidence_score": confidence,
        "engine_used": engine_used,
        "believe_status": "ACTIVE",
        "believe_direction": believe or "WAIT",
        "s30_direction": s30 or "UNKNOWN",
        "m1_direction": "NOT_USED_BY_BELIEVE",
        "m5_direction": "NOT_USED_BY_BELIEVE",
        "m1_bias": "NOT_USED_BY_BELIEVE",
        "m5_bias": "NOT_USED_BY_BELIEVE",
        "m5_regime": "NOT_USED_BY_BELIEVE",
        "m1_adx": None,
        "risk_level": "NOT_EVALUATED",
        "data_quality": "NOT_EVALUATED",
        "extreme_believe_active": extreme_active,
        "core_conditions": core,
        "secondary_conditions": {
            "divergence_aligned": divergence_aligned,
            "macd_zero_aligned": macd_zero_aligned,
        },
        "risk_filters": filters,
        "conditions_met": action != "WAIT",
        "failed_conditions": failed,
        "reason_th": reason_th,
    }
