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


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load_bundle(path: str | None = None) -> Artifacts:
    adir = artifacts_dir(path)
    booster = lgb.Booster(model_file=str(adir / MODEL_FILE))
    with open(adir / CALIBRATOR_FILE, "rb") as f:
        calibrator: Calibrator = pickle.load(f)
    meta = json.loads((adir / FEATURE_META_FILE).read_text())

    return Artifacts(
        booster=booster,
        calibrator=calibrator,
        feature_names=meta["feature_order"],
        categorical_features=meta["categorical_features"],
        categories=meta["categorical_levels"],
        best_iteration=int(meta["model"]["best_iteration"]),
        scale_pos_weight=float(meta["model"]["scale_pos_weight"]),
        baseline=BaseRateBaseline.from_dict(meta["baseline"]),
    )


# ---------------------------------------------------------------------------
# THE reference scoring function (serving + tests share this)
# ---------------------------------------------------------------------------
def predict_proba_one(
    artifacts: Artifacts,
    feature_dict: dict,
    k_factors: int = 3,
    with_factors: bool = True,
) -> dict:
    """Score a single flight. Returns a dict shaped for ``/api/predict``.

    ``feature_dict`` must contain all ``MODEL_FEATURES`` keys (pre-departure-safe
    by construction). Returns::

        {
          "delay_probability": float,   # calibrated
          "risk_band": "low|moderate|high",
          "baseline_probability": float,
          "beats_baseline": bool,
          "calibrated": True,
          "top_factors": [ {feature, value, contribution, direction}, ... ],
        }

    This is the canonical scoring path; the serving layer imports it directly.
    """
    missing = [c for c in MODEL_FEATURES if c not in feature_dict]
    if missing:
        raise ValueError(f"feature_dict missing model features: {missing}")

    row = pd.DataFrame([{c: feature_dict[c] for c in MODEL_FEATURES}])
    x = coerce_dtypes(row, artifacts.categories)[MODEL_FEATURES]
    raw = float(artifacts.booster.predict(
        x, num_iteration=artifacts.best_iteration or None
    )[0])
    calibrated = float(artifacts.calibrator.transform(np.array([raw]))[0])

    base = artifacts.baseline.predict_one(
        feature_dict["origin"], feature_dict["dest"]
    )

    result = {
        "delay_probability": round(calibrated, 6),
        "risk_band": risk_band(calibrated),
        "baseline_probability": round(float(base), 6),
        "beats_baseline": bool(calibrated > base) == (calibrated > base),  # informational
        "calibrated": True,
    }
    # "beats_baseline" in the API means: does the model deviate meaningfully from
    # the naive route base rate (i.e. it is adding information). We report whether
    # the model's risk differs from the route prior.
    result["beats_baseline"] = bool(abs(calibrated - base) > 1e-6)

    if with_factors:
        expl = artifacts.ensure_explainer()
        result["top_factors"] = top_factors(expl, row, k=k_factors)

    return result
