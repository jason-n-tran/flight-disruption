"""Evaluation on the held-out TEST year: ranking, calibration, and vs-baseline.

Metrics reported:
  * ROC-AUC and PR-AUC (average precision) — PR-AUC matters most under imbalance.
  * Brier score (calibration quality) for raw and calibrated probabilities.
  * A reliability/calibration curve, saved as JSON data + a matplotlib PNG.
  * The base-rate baseline's ROC-AUC / PR-AUC, and the model's lift over it.

Everything lands in ``ml/reports/`` (metrics.json, calibration_curve.{json,png}).
The headline "model beats baseline by X" line is printed and stored.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

from .config import CALIBRATION_DATA, CALIBRATION_PNG, METRICS_FILE, reports_dir


@dataclass
class EvalMetrics:
    n_test: int
    test_positive_rate: float
    model_roc_auc: float
    model_pr_auc: float
    model_brier_raw: float
    model_brier_calibrated: float
    baseline_roc_auc: float
    baseline_pr_auc: float
    baseline_brier: float
    roc_auc_lift: float
    pr_auc_lift: float
    beats_baseline: bool
    calib_brier_before: float
    calib_brier_after: float


def _safe_auc(y: np.ndarray, p: np.ndarray) -> float:
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, p))


def reliability_curve(y_true: np.ndarray, proba: np.ndarray, n_bins: int = 10) -> dict:
    """Equal-width binned reliability curve: mean predicted vs observed per bin."""
    y = np.asarray(y_true, dtype="float64")
    p = np.asarray(proba, dtype="float64")
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    mean_pred, frac_pos, counts = [], [], []
    for b in range(n_bins):
        mask = idx == b
        c = int(mask.sum())
        counts.append(c)
        if c == 0:
            mean_pred.append(None)
            frac_pos.append(None)
        else:
            mean_pred.append(float(p[mask].mean()))
            frac_pos.append(float(y[mask].mean()))
    return {
        "bin_edges": bins.tolist(),
        "mean_predicted": mean_pred,
        "fraction_positive": frac_pos,
        "counts": counts,
    }
