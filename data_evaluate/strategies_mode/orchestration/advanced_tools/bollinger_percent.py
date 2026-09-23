"""Pure in-memory Bollinger %B calculation."""

import math
from numbers import Real
from typing import NamedTuple

import pandas as pd


DEFAULT_PERIOD = 41
DEFAULT_STD_DEV = 2.0


class BollingerPercentResult(NamedTuple):
    """Latest Bollinger values for one close series."""

    middle: float
    upper: float
    lower: float
    width: float
    percent_b: float
    close: float


def calculate_bollinger_percent(
    close_series: pd.Series,
    period: int = DEFAULT_PERIOD,
    std_dev: float = DEFAULT_STD_DEV,
) -> BollingerPercentResult:
    """Calculate the latest SMA Bollinger %B value from in-memory closes."""
    if not isinstance(close_series, pd.Series):
        raise TypeError("FAIL-FAST: close_series must be a pandas Series")
    if not isinstance(period, int) or isinstance(period, bool) or period <= 0:
        raise ValueError("FAIL-FAST: Bollinger period must be a positive integer")
    if not isinstance(std_dev, Real) or isinstance(std_dev, bool):
        raise TypeError("FAIL-FAST: Bollinger standard deviation must be numeric")
    if not math.isfinite(float(std_dev)) or float(std_dev) <= 0:
        raise ValueError("FAIL-FAST: Bollinger standard deviation must be finite and positive")
    if close_series.empty:
        raise ValueError("FAIL-FAST: close series is empty")
    if not pd.api.types.is_numeric_dtype(close_series.dtype):
        raise TypeError("FAIL-FAST: close series must contain numeric values")
    if len(close_series) < period:
        raise ValueError(f"FAIL-FAST: need at least {period} closes for Bollinger %B")

    close = close_series.astype("float64")
    if close.isna().any() or not bool(close.map(math.isfinite).all()):
        raise ValueError("FAIL-FAST: close series contains NaN or infinite values")

    window = close.tail(period)
    middle = float(window.mean())
    std = float(window.std(ddof=0))
    upper = middle + (float(std_dev) * std)
    lower = middle - (float(std_dev) * std)
    width = upper - lower
    if not math.isfinite(upper) or not math.isfinite(lower) or not math.isfinite(width):
        raise ValueError("FAIL-FAST: Bollinger bands contain NaN or infinite values")
    if width <= 0:
        raise ValueError("FAIL-FAST: Bollinger band width is zero or collapsed")

    latest_close = float(close.iloc[-1])
    percent_b = (latest_close - lower) / width
    if not math.isfinite(percent_b):
        raise ValueError("FAIL-FAST: Bollinger %B is NaN or infinite")
    return BollingerPercentResult(
        middle=middle,
        upper=upper,
        lower=lower,
        width=width,
        percent_b=percent_b,
        close=latest_close,
    )
