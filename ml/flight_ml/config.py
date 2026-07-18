"""Shared constants and small helpers for the ML pipeline.

Feature definitions, the label, and the train/test year split all come from the
single source of truth in ``flight_contracts.contract`` — this module only adds
ML-pipeline-local concerns (identity columns, artifact filenames, output dirs).
"""

from __future__ import annotations

import os
from pathlib import Path

from flight_contracts.contract import (  # noqa: F401  (re-exported for convenience)
    CATEGORICAL_FEATURES,
    GOLD_FEATURES_TABLE,
    LABEL_COLUMN,
    MODEL_FEATURES,
    NUMERIC_FEATURES,
    TEST_YEARS,
    TRAIN_YEARS,
)

# Identity / bookkeeping columns that travel with the gold table but are NOT
# model features. Kept for split logic, baseline grouping, and traceability.
IDENTITY_COLUMNS = ["flight_date", "year", "origin", "dest", "carrier"]

# The temporal validation slice is carved from the END of the train period
# (last fraction of the latest train year) for early stopping; the calibration
# slice is also temporal. Both are leakage-safe by construction.
VALID_FRACTION = 0.15   # fraction of train rows (most recent) used for early stop
CALIB_FRACTION = 0.15   # fraction of train rows (most recent, after valid) for calibration

# Artifact filenames (the serving layer + sample generator depend on these names).
MODEL_FILE = "model.lgb"
CALIBRATOR_FILE = "calibrator.pkl"
FEATURE_META_FILE = "feature_metadata.json"
ONNX_FILE = "model.onnx"

# Report filenames.
METRICS_FILE = "metrics.json"
CALIBRATION_PNG = "calibration_curve.png"
CALIBRATION_DATA = "calibration_curve.json"


def package_root() -> Path:
    """Directory of the installed ``ml/`` component (parent of ``flight_ml``)."""
    return Path(__file__).resolve().parent.parent


def artifacts_dir(out: str | os.PathLike | None = None) -> Path:
    d = Path(out) if out is not None else package_root() / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reports_dir(out: str | os.PathLike | None = None) -> Path:
    d = Path(out) if out is not None else package_root() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def risk_band(prob: float) -> str:
    """Shared risk-band thresholds (mirrors api_contract.md)."""
    if prob < 0.20:
        return "low"
    if prob < 0.45:
        return "moderate"
    return "high"
