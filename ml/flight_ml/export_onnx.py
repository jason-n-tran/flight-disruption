"""ONNX export + portability test (a SHOWCASE / MLOps artifact).

IMPORTANT FRAMING
-----------------
The *serving* path uses the **native LightGBM booster** (so SHAP TreeExplainer
can produce live ``top_factors``). ONNX is exported as a portability / MLOps
showcase: "the model runs anywhere onnxruntime runs, no Python/LightGBM needed".
We prove that with a portability test: load the ONNX model in onnxruntime, score
rows, and assert predictions match the native booster within tolerance.

Categorical encoding note
-------------------------
onnxmltools converts LightGBM into a numeric tree ensemble. To keep the native
and ONNX models scoring the *same* function, we feed BOTH a float matrix of the
pandas categorical *codes* (origin->0,1,2...) using the SAME category level sets
pinned in training. The exported ``feature_metadata.json`` records the codes, so
any ONNX consumer can reproduce the encoding. This is exactly how a portable
deployment would have to encode categoricals anyway.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import CATEGORICAL_FEATURES, MODEL_FEATURES, ONNX_FILE, artifacts_dir
from .data import coerce_dtypes
from .train import TrainedModel


def encode_codes(df: pd.DataFrame, categories: dict[str, list]) -> np.ndarray:
    """Encode rows to a float32 matrix of categorical codes + numeric values.

    Uses the pinned category level sets so codes are stable across native/ONNX.
    Unseen categories -> -1 (LightGBM treats negative as the missing category).
    """
    coerced = coerce_dtypes(df, categories)
    out = pd.DataFrame(index=coerced.index)
    for col in MODEL_FEATURES:
        if col in CATEGORICAL_FEATURES:
            out[col] = coerced[col].cat.codes.astype("float32")
        else:
            out[col] = coerced[col].astype("float32")
    return out[MODEL_FEATURES].to_numpy(dtype=np.float32)


def _native_proba_from_codes(model: TrainedModel, codes: np.ndarray) -> np.ndarray:
    """Score the native booster directly on the raw code matrix (pandas-free).

    This matches what ONNX sees: a plain float32 matrix where categorical columns
    hold integer codes. We pass a *numpy array* (not a DataFrame) so LightGBM does
    NOT try to reconcile pandas categorical dtypes against its stored
    ``pandas_categorical`` map — it treats the columns positionally and uses the
    same numeric split thresholds the ONNX graph encodes. This is the
    apples-to-apples comparison for the portability test.
    """
    preds = model.booster.predict(
        np.asarray(codes, dtype=np.float64),
        num_iteration=model.best_iteration or None,
    )
    return np.asarray(preds, dtype="float64")
