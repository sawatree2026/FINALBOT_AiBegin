"""Disk-backed Believe strategy analyzer for strategies_mode."""

from typing import Any, Dict, Optional


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
    for raw_line in lines:
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        if normalized_key:
            fields[normalized_key] = value.strip().strip("'\"")
    return fields


def _parse_bool(val: Any) -> bool:
    return str(val or "").strip().upper() in {"TRUE", "1", "YES"}


def _parse_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def analyze_payload_file(symbol: str, payload_path: str) -> Dict[str, Any]:
    """Evaluate Believe strategy directly against Part 2 single-pass payload."""
    fields = _read_fields(payload_path)

    payload_id = fields.get("id") or payload_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    bias = fields.get("bias", "NEUTRAL").upper()
    bb_b = _parse_float(fields.get("bb_percent_b"), 0.5)
    bb_touch = fields.get("bb_percent_touch", "NONE").upper()
    sto_k = _parse_float(fields.get("sto_k"), 50.0)
    sto_d = _parse_float(fields.get("sto_d"), 50.0)
    sto_zone = fields.get("sto_zone", "NEUTRAL").upper()
    sto_cross = fields.get("sto_cross", "NONE").upper()
    sto_cross_50 = _parse_bool(fields.get("sto_cross_50"))
    sto_hook = _parse_bool(fields.get("sto_hook_confirmed"))
    sto_tangled = _parse_bool(fields.get("sto_tangled"))
    ma_fast = _parse_float(fields.get("ma_fast"), 0.0)
    ma_slow = _parse_float(fields.get("ma_slow"), 0.0)
    ma_cross = fields.get("ma_cross", "NONE").upper()
    ma_confirmed = _parse_bool(fields.get("ma_cross_confirmed"))
    grid_block = _parse_bool(fields.get("grid_block_ahead"))
    sr_block = _parse_bool(fields.get("sr_block_ahead"))
    window_clear = _parse_bool(fields.get("window_clear", "TRUE"))
    is_gray = _parse_bool(fields.get("is_gray_candle"))

    risk_clear = not grid_block and not sr_block and window_clear and not sto_tangled

    # Check CALL setup
    call_ma = ma_cross in ("GOLDEN_CROSS", "BULLISH", "UP") or (bias == "BULLISH" and ma_fast > ma_slow and ma_confirmed)
    call_bb = bb_b <= 0.45 or bb_touch in ("LOWER", "LOWER_0", "NONE")
    call_sto = (
        "OVERSOLD" in sto_zone
        or sto_k <= 35.0
        or sto_hook
        or sto_cross in ("GOLDEN_CROSS", "BULLISH", "UP")
        or sto_cross_50
    )
    is_call = call_ma and call_bb and call_sto and risk_clear and not is_gray

    # Check PUT setup
    put_ma = ma_cross in ("DEATH_CROSS", "BEARISH", "DOWN") or (bias == "BEARISH" and ma_fast < ma_slow and ma_confirmed)
    put_bb = bb_b >= 0.55 or bb_touch in ("UPPER", "UPPER_1", "NONE")
    put_sto = (
        "OVERBOUGHT" in sto_zone
        or sto_k >= 65.0
        or sto_hook
        or sto_cross in ("DEATH_CROSS", "BEARISH", "DOWN")
        or sto_cross_50
    )
    is_put = put_ma and put_bb and put_sto and risk_clear and not is_gray

    if is_call:
        action = "CALL"
        confidence = 85.0 if (sto_hook or ma_cross == "GOLDEN_CROSS") else 75.0
        reason_th = "เข้าเงื่อนไข Believe CALL: BB แตะล่าง + Stochastic Oversold + MA Golden Cross ผ่านตัวกรองความเสี่ยง"
    elif is_put:
        action = "PUT"
        confidence = 85.0 if (sto_hook or ma_cross == "DEATH_CROSS") else 75.0
        reason_th = "เข้าเงื่อนไข Believe PUT: BB แตะบน + Stochastic Overbought + MA Death Cross ผ่านตัวกรองความเสี่ยง"
    else:
        action = "WAIT"
        confidence = 0.0
        reason_th = "รอสัญญาณ Believe: ยังไม่ครบเงื่อนไขจุดเข้า (BB/Stochastic/MA)"

    return {
        "ID": payload_id,
        "symbol": symbol,
        "action": action,
        "expiry_minutes": 3,
        "confidence_score": confidence,
        "engine_used": "STRATEGY_BELIEVE",
        "bias": bias,
        "ma_cross": ma_cross,
        "sto_zone": sto_zone,
        "bb_touch": bb_touch,
        "window_clear": window_clear,
        "conditions_met": action in ("CALL", "PUT"),
        "reason_th": reason_th,
    }
