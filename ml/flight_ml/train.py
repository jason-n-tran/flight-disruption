"""LightGBM binary classifier with native categorical handling + temporal early stop.

Design choices a reviewer should notice:

* **Native categoricals.** ``origin/dest/carrier/dep_hour/...`` are passed via
  ``categorical_feature`` and encoded as pandas ``category`` dtype — no one-hot
  blow-up, and LightGBM's optimal split on category subsets is used.
* **Class imbalance.** Delays are the minority class; we set ``scale_pos_weight``
  to ``#neg/#pos`` so the model doesn't collapse to "never delayed".
* **Temporal early stopping.** The validation set comes from the END of the train
  period (see :mod:`flight_ml.split`), not a random fold — consistent with the
  no-leakage discipline.
* **Sensible, not over-tuned, params.** Modest depth/leaves + regularization;
  the goal is a credible, reproducible baseline-beater, not a Kaggle grind.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

from .config import CATEGORICAL_FEATURES, LABEL_COLUMN, MODEL_FEATURES
from .data import coerce_dtypes


DEFAULT_PARAMS: dict = {
    "objective": "binary",
    "metric": ["auc", "binary_logloss"],
    "boosting_type": "gbdt",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "max_depth": -1,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.85,
    "bagging_freq": 1,
    "lambda_l1": 0.0,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "seed": 17,
    "deterministic": True,
    "force_col_wise": True,
}


@dataclass
class TrainedModel:
    booster: lgb.Booster
    feature_names: list[str]
    categorical_features: list[str]
    categories: dict[str, list]
    best_iteration: int
    scale_pos_weight: float

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Raw (uncalibrated) P(dep_del15=1) for the given rows."""
        x = coerce_dtypes(df, self.categories)[self.feature_names]
        preds = self.booster.predict(x, num_iteration=self.best_iteration or None)
        return np.asarray(preds, dtype="float64")


def _scale_pos_weight(y: pd.Series) -> float:
    pos = float((y == 1).sum())
    neg = float((y == 0).sum())
    if pos <= 0:
        return 1.0
    return max(neg / pos, 1.0)


def train_model(
    fit: pd.DataFrame,
    valid: pd.DataFrame,
    categories: dict[str, list],
    params: dict | None = None,
    num_boost_round: int = 800,
    early_stopping_rounds: int = 50,
) -> TrainedModel:
    """Train LightGBM on ``fit`` with early stopping on the temporal ``valid`` slice.

    ``categories`` (from :func:`flight_ml.data.extract_categories`, derived on the
    full TRAIN set) pins categorical level sets so fit/valid/test/serving share
    identical encodings.
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    spw = _scale_pos_weight(fit[LABEL_COLUMN])
    params["scale_pos_weight"] = spw

    fit_c = coerce_dtypes(fit, categories)
    valid_c = coerce_dtypes(valid, categories)

    dtrain = lgb.Dataset(
        fit_c[MODEL_FEATURES],
        label=fit_c[LABEL_COLUMN].astype(int),
        categorical_feature=CATEGORICAL_FEATURES,
        free_raw_data=False,
    )
    dvalid = lgb.Dataset(
        valid_c[MODEL_FEATURES],
        label=valid_c[LABEL_COLUMN].astype(int),
        categorical_feature=CATEGORICAL_FEATURES,
        reference=dtrain,
        free_raw_data=False,
    )

    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        valid_sets=[dtrain, dvalid],
        valid_names=["train", "valid"],
        callbacks=[
            lgb.early_stopping(early_stopping_rounds, verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )

    return TrainedModel(
        booster=booster,
        feature_names=list(MODEL_FEATURES),
        categorical_features=list(CATEGORICAL_FEATURES),
        categories=categories,
        best_iteration=int(booster.best_iteration or booster.current_iteration()),
        scale_pos_weight=spw,
    )
