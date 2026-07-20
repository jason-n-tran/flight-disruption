"""Artifact bundle: what the serving layer + sample generator consume.

Writes to ``ml/artifacts/``:
  * ``model.lgb``            — the native LightGBM booster (text format).
  * ``calibrator.pkl``       — the fitted probability calibrator.
  * ``feature_metadata.json``— feature order, categorical levels + codes, dtypes,
                               the baseline route table + global prior, model
                               metadata (best_iteration, scale_pos_weight).
  * (``model.onnx``)         — written by :mod:`export_onnx` (showcase).

The single reference scoring function :func:`predict_proba_one` is used by BOTH
serving and the tests, so there is exactly one definition of "how to score a
flight" in the codebase. It returns the calibrated probability AND the SHAP
``top_factors`` shape from the api_contract.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .baseline import BaseRateBaseline
from .calibrate import Calibrator
from .config import (
    CALIBRATOR_FILE,
    CATEGORICAL_FEATURES,
    FEATURE_META_FILE,
    MODEL_FEATURES,
    MODEL_FILE,
    NUMERIC_FEATURES,
    artifacts_dir,
    risk_band,
)
from .data import coerce_dtypes
from .explain import Explainer, build_explainer, top_factors
from .train import TrainedModel


@dataclass
class Artifacts:
    """In-memory handle to a loaded artifact bundle (used by serving + tests)."""

    booster: lgb.Booster
    calibrator: Calibrator
    feature_names: list[str]
    categorical_features: list[str]
    categories: dict[str, list]
    best_iteration: int
    scale_pos_weight: float
    baseline: BaseRateBaseline
    explainer: Explainer | None = None

    def ensure_explainer(self) -> Explainer:
        if self.explainer is None:
            tm = TrainedModel(
                booster=self.booster,
                feature_names=self.feature_names,
                categorical_features=self.categorical_features,
                categories=self.categories,
                best_iteration=self.best_iteration,
                scale_pos_weight=self.scale_pos_weight,
            )
            self.explainer = build_explainer(tm)
        return self.explainer


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
def save_bundle(
    model: TrainedModel,
    calibrator: Calibrator,
    baseline: BaseRateBaseline,
    out: str | None = None,
) -> Path:
    adir = artifacts_dir(out)

    model.booster.save_model(
        str(adir / MODEL_FILE), num_iteration=model.best_iteration or None
    )

    with open(adir / CALIBRATOR_FILE, "wb") as f:
        pickle.dump(calibrator, f)

    meta = {
        "feature_order": list(MODEL_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "numeric_features": list(NUMERIC_FEATURES),
        "label_column": "dep_del15",
        "dtypes": {
            **{c: "category" for c in CATEGORICAL_FEATURES},
            **{c: "float64" for c in NUMERIC_FEATURES},
        },
        # category levels + their integer codes (index in list == code)
        "categorical_levels": {
            c: list(model.categories.get(c, [])) for c in CATEGORICAL_FEATURES
        },
        "model": {
            "type": "lightgbm",
            "best_iteration": model.best_iteration,
            "scale_pos_weight": model.scale_pos_weight,
        },
        "calibration": {
            "method": calibrator.method,
            "brier_before": calibrator.brier_before,
            "brier_after": calibrator.brier_after,
        },
        "baseline": baseline.to_dict(),
    }
    (adir / FEATURE_META_FILE).write_text(json.dumps(meta, indent=2))
    return adir
