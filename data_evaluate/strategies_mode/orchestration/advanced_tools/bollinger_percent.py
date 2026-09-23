from dataclasses import dataclass

import numpy as np
import pandas as pd


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


def calculate_bollinger_percent(
    close_series: pd.Series,
    period: int = DEFAULT_PERIOD,
    std_dev: float = DEFAULT_STD_DEV,
) -> BollingerPercentResult:
    """Calculate SMA Bollinger %B from one in-memory close series."""
    if not isinstance(close_series, pd.Series):
        raise TypeError("FAIL-FAST: close_series must be a pandas Series")
    if not isinstance(period, int) or isinstance(period, bool) or period <= 0:
        raise ValueError("FAIL-FAST: Bollinger period must be a positive integer")
    if not isinstance(std_dev, (int, float)) or isinstance(std_dev, bool):
        raise TypeError("FAIL-FAST: Bollinger standard deviation must be numeric")
    if not np.isfinite(float(std_dev)) or float(std_dev) <= 0:
        raise ValueError("FAIL-FAST: Bollinger standard deviation must be finite and positive")
    if len(close_series) < period:
        raise ValueError(f"FAIL-FAST: need at least {period} candles for Bollinger %B")

    close = pd.to_numeric(close_series, errors="coerce")
    values = close.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("FAIL-FAST: close series contains NaN/inf")

    middle = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + (float(std_dev) * std)
    lower = middle - (float(std_dev) * std)

    latest_middle = float(middle.iloc[-1])
    latest_upper = float(upper.iloc[-1])
    latest_lower = float(lower.iloc[-1])
    latest_close = float(close.iloc[-1])
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
