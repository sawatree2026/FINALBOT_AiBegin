from dataclasses import dataclass

import numpy as np


PERIOD_K = 13
SMOOTHING = 10
PERIOD_D = 3
OVERBOUGHT = 90.0
OVERSOLD = 10.0


@dataclass(frozen=True)
class StochasticResult:
    k: float
    d: float
    zone: str
    cross: str
    cross_50: str
    hook_confirmed: bool
    tangled: bool


def assemble_stochastic(base: dict) -> StochasticResult:
    required = ("k", "d", "previous_k", "previous_d", "recent_gap")
    if not isinstance(base, dict) or any(key not in base for key in required):
        raise ValueError("FAIL-FAST: incomplete S30 Stochastic basis")
    values = tuple(float(base[key]) for key in required)
    if not all(np.isfinite(value) for value in values):
        raise ValueError("FAIL-FAST: S30 Stochastic basis contains NaN/inf")
    k, d, previous_k, previous_d, recent_gap = values
    cross = "UP" if previous_k <= previous_d and k > d else (
        "DOWN" if previous_k >= previous_d and k < d else "NONE"
    )
    cross_50 = "UP" if previous_k < 50 <= k else (
        "DOWN" if previous_k > 50 >= k else "NONE"
    )
    zone = "OVERSOLD_10" if k <= OVERSOLD else (
        "OVERBOUGHT_90" if k >= OVERBOUGHT else "MID"
    )
    return StochasticResult(
        k=k,
        d=d,
        zone=zone,
        cross=cross,
        cross_50=cross_50,
        hook_confirmed=cross != "NONE",
        tangled=recent_gap < 2,
    )
