"""Forecast accuracy metrics. All take aligned 1-D numpy arrays."""
from __future__ import annotations

import numpy as np


def wape(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Weighted absolute percentage error: sum|e| / sum|actual|."""
    denom = np.abs(actual).sum()
    if denom == 0:
        return float("nan")
    return float(np.abs(actual - forecast).sum() / denom)


def smape(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Symmetric MAPE in [0, 2]; zero-zero pairs contribute 0."""
    denom = (np.abs(actual) + np.abs(forecast)) / 2.0
    mask = denom > 0
    if not mask.any():
        return float("nan")
    return float((np.abs(actual - forecast)[mask] / denom[mask]).mean())


def bias(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Signed relative bias: sum(forecast - actual) / sum|actual|.
    Positive = over-forecasting."""
    denom = np.abs(actual).sum()
    if denom == 0:
        return float("nan")
    return float((forecast - actual).sum() / denom)


def pinball(actual: np.ndarray, forecast: np.ndarray, alpha: float) -> float:
    """Mean pinball (quantile) loss for quantile level alpha."""
    diff = actual - forecast
    return float(np.maximum(alpha * diff, (alpha - 1) * diff).mean())
