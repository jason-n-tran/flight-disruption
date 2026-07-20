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


def evaluate(
    y_test: np.ndarray,
    model_raw: np.ndarray,
    model_calibrated: np.ndarray,
    baseline_proba: np.ndarray,
    calib_brier_before: float,
    calib_brier_after: float,
    out: str | None = None,
) -> EvalMetrics:
    """Compute metrics, write reports, and return the metrics dataclass."""
    y = np.asarray(y_test, dtype="int")

    model_roc = _safe_auc(y, model_calibrated)
    model_pr = float(average_precision_score(y, model_calibrated))
    base_roc = _safe_auc(y, baseline_proba)
    base_pr = float(average_precision_score(y, baseline_proba))

    metrics = EvalMetrics(
        n_test=int(len(y)),
        test_positive_rate=float(y.mean()),
        model_roc_auc=model_roc,
        model_pr_auc=model_pr,
        model_brier_raw=float(brier_score_loss(y, model_raw)),
        model_brier_calibrated=float(brier_score_loss(y, model_calibrated)),
        baseline_roc_auc=base_roc,
        baseline_pr_auc=base_pr,
        baseline_brier=float(brier_score_loss(y, baseline_proba)),
        roc_auc_lift=model_roc - base_roc,
        pr_auc_lift=model_pr - base_pr,
        beats_baseline=bool(model_roc > base_roc and model_pr > base_pr),
        calib_brier_before=float(calib_brier_before),
        calib_brier_after=float(calib_brier_after),
    )

    rdir = reports_dir(out)
    curve = reliability_curve(y, model_calibrated)
    (rdir / CALIBRATION_DATA).write_text(json.dumps(curve, indent=2))
    _save_calibration_png(curve, rdir / CALIBRATION_PNG)
    (rdir / METRICS_FILE).write_text(json.dumps(asdict(metrics), indent=2))

    return metrics


def _save_calibration_png(curve: dict, path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [v for v in curve["mean_predicted"] if v is not None]
    ys = [
        curve["fraction_positive"][i]
        for i, v in enumerate(curve["mean_predicted"])
        if v is not None
    ]
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfectly calibrated")
    ax.plot(xs, ys, "o-", color="#1f77b4", label="model (calibrated)")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed delay fraction")
    ax.set_title("Calibration curve (test set)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def format_summary(m: EvalMetrics) -> str:
    verdict = "BEATS" if m.beats_baseline else "does NOT beat"
    return (
        f"Model {verdict} baseline | "
        f"ROC-AUC {m.model_roc_auc:.4f} vs {m.baseline_roc_auc:.4f} "
        f"(+{m.roc_auc_lift:.4f}) | "
        f"PR-AUC {m.model_pr_auc:.4f} vs {m.baseline_pr_auc:.4f} "
        f"(+{m.pr_auc_lift:.4f}) | "
        f"Brier raw {m.model_brier_raw:.4f} -> calibrated {m.model_brier_calibrated:.4f}"
    )
