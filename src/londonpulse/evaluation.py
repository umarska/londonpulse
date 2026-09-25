"""Explicit forecast scores and empirical chronological calibration."""

from __future__ import annotations

import math
import numpy as np


def metrics(actual, predicted) -> dict[str, float]:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metrics require matching finite observations and predictions.")
    error = predicted - actual
    denominator = np.abs(actual) + np.abs(predicted)
    smape_terms = np.divide(2 * np.abs(error), denominator, out=np.zeros_like(error), where=denominator > 0)
    total = np.abs(actual).sum()
    return {"mae": float(np.abs(error).mean()), "rmse": float(np.sqrt(np.square(error).mean())),
            "wape": float(100 * np.abs(error).sum() / total) if total > 0 else (0.0 if np.abs(error).sum() == 0 else None),
            "smape": float(100 * smape_terms.mean())}


def finite_sample_radius(residuals, nominal_coverage: float = 0.9) -> tuple[float, int]:
    """Order statistic with finite-sample rank correction; no IID claim for time series."""
    values = np.asarray(residuals, dtype=float)
    if not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Calibration requires finite absolute errors.")
    rank = math.ceil((len(values) + 1) * nominal_coverage)
    if rank > len(values):
        raise ValueError("Not enough calibration observations for this finite rank.")
    return float(np.sort(values)[rank - 1]), rank
