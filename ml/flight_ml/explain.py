"""SHAP explainability — powers the API's signed ``top_factors``.

A ``shap.TreeExplainer`` over the native LightGBM booster gives exact, additive
per-feature contributions. The serving layer runs :func:`top_factors` LIVE on a
single feature row, so this is built to be importable and fast (TreeExplainer on
a tree model is microseconds per row).

``top_factors`` returns the api_contract shape exactly:
``{feature, value, contribution, direction}`` where ``direction`` is
``"increases"`` if the contribution pushes delay probability up, else
``"decreases"``. Contributions are in LightGBM's raw (log-odds) margin space; we
report the signed value directly — sign and relative magnitude are what the UI
shows, and they are correct in margin space.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from .config import MODEL_FEATURES
from .data import coerce_dtypes
from .train import TrainedModel


@dataclass
class Explainer:
    """Wraps a SHAP TreeExplainer bound to a trained LightGBM model."""

    tree_explainer: shap.TreeExplainer
    feature_names: list[str]
    categories: dict[str, list]

    def shap_values(self, df: pd.DataFrame) -> np.ndarray:
        """Per-row, per-feature SHAP contributions (margin space), shape (n, n_feat)."""
        x = coerce_dtypes(df, self.categories)[self.feature_names]
        vals = self.tree_explainer.shap_values(x)
        # SHAP returns different shapes across versions for binary LightGBM:
        #   * list[array]            -> [neg, pos]; take positive class
        #   * 3D array (n, feat, 2)  -> last axis is class; take positive class
        #   * 2D array (n, feat)     -> already the (positive-class) margin
        if isinstance(vals, list):
            vals = vals[-1]
        vals = np.asarray(vals)
        if vals.ndim == 3:
            vals = vals[:, :, -1]
        return vals


def build_explainer(model: TrainedModel) -> Explainer:
    expl = shap.TreeExplainer(model.booster)
    return Explainer(
        tree_explainer=expl,
        feature_names=list(model.feature_names),
        categories=model.categories,
    )
