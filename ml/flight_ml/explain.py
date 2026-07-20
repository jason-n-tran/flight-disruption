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


def top_factors(
    explainer: Explainer,
    feature_row: dict | pd.Series | pd.DataFrame,
    k: int = 3,
) -> list[dict]:
    """Return the signed top-k feature contributors for ONE flight.

    Output matches api_contract ``top_factors``::

        [{"feature": "origin_wind_gusts", "value": 41.2,
          "contribution": 0.08, "direction": "increases"}, ...]

    ``value`` is the raw feature value as supplied (numeric or category label).
    Sorted by absolute contribution, descending.
    """
    row_df = _as_one_row_df(feature_row)
    shap_vals = explainer.shap_values(row_df)[0]  # (n_feat,)

    order = np.argsort(np.abs(shap_vals))[::-1][:k]
    factors: list[dict] = []
    for i in order:
        feat = explainer.feature_names[i]
        raw_val = row_df.iloc[0][feat]
        contribution = float(shap_vals[i])
        factors.append(
            {
                "feature": feat,
                "value": _jsonable(raw_val),
                "contribution": round(contribution, 6),
                "direction": "increases" if contribution >= 0 else "decreases",
            }
        )
    return factors


def _as_one_row_df(feature_row) -> pd.DataFrame:
    if isinstance(feature_row, pd.DataFrame):
        df = feature_row.iloc[[0]].copy()
    elif isinstance(feature_row, pd.Series):
        df = feature_row.to_frame().T.copy()
    else:  # dict
        df = pd.DataFrame([feature_row])
    missing = [c for c in MODEL_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"feature_row missing model features: {missing}")
    return df[MODEL_FEATURES]


def _jsonable(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if pd.isna(v):
        return None
    return v
