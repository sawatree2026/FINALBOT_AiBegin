from dataclasses import dataclass

import numpy as np


DEFAULT_PERIOD = 41
DEFAULT_STD_DEV = 2.0


@dataclass(frozen=True)
class BollingerPercentResult:
    middle: float
    upper: float
    lower: float
    width: float
    percent_b: float
    close: float


def assemble_bollinger_percent(
    close: float,
    middle: float,
    std: float,
    period: int = DEFAULT_PERIOD,
    std_dev: float = DEFAULT_STD_DEV,
) -> BollingerPercentResult:
    """Assemble %B from S30 basis values produced by IndicatorStore."""
    if period != DEFAULT_PERIOD:
        raise ValueError("FAIL-FAST: S30 Bollinger %B requires period 41")
    if not isinstance(std_dev, (int, float)) or isinstance(std_dev, bool):
        raise TypeError("FAIL-FAST: Bollinger standard deviation must be numeric")
    if not np.isfinite(float(std_dev)) or float(std_dev) <= 0:
        raise ValueError("FAIL-FAST: Bollinger standard deviation must be finite and positive")
    if float(std_dev) != DEFAULT_STD_DEV:
        raise ValueError("FAIL-FAST: S30 Bollinger %B requires standard deviation 2")
    values = (float(close), float(middle), float(std))
    if not all(np.isfinite(value) for value in values):
        raise ValueError("FAIL-FAST: Bollinger basis contains NaN/inf")
    latest_close, latest_middle, latest_std = values
    latest_upper = latest_middle + (float(std_dev) * latest_std)
    latest_lower = latest_middle - (float(std_dev) * latest_std)
    width = latest_upper - latest_lower
    if not all(np.isfinite(value) for value in (
        latest_middle,
        latest_upper,
        latest_lower,
        latest_close,
        width,
    )):
        raise ValueError("FAIL-FAST: Bollinger values contain NaN/inf")
    if width <= 0:
        raise ValueError("FAIL-FAST: Bollinger band width is zero - %B is undefined")

    percent_b = (latest_close - latest_lower) / width
    if not np.isfinite(percent_b):
        raise ValueError("FAIL-FAST: Bollinger %B is NaN/inf")

    return BollingerPercentResult(
        middle=latest_middle,
        upper=latest_upper,
        lower=latest_lower,
        width=width,
        percent_b=float(percent_b),
        close=latest_close,
    )
