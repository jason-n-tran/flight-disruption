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


def export_onnx(model: TrainedModel, out: str | None = None) -> Path:
    """Convert the LightGBM booster to ONNX and write ``model.onnx``."""
    from onnxmltools import convert_lightgbm
    from onnxmltools.convert.common.data_types import FloatTensorType

    n_features = len(MODEL_FEATURES)
    initial_types = [("input", FloatTensorType([None, n_features]))]
    onnx_model = convert_lightgbm(
        model.booster,
        initial_types=initial_types,
        zipmap=False,
        target_opset=None,
    )
    path = artifacts_dir(out) / ONNX_FILE
    with open(path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    return path


def portability_test(
    model: TrainedModel,
    sample: pd.DataFrame,
    onnx_path: str | Path | None = None,
    out: str | None = None,
    atol: float = 1e-4,
) -> dict:
    """Load ONNX in onnxruntime, score ``sample``, assert it matches native.

    Returns a dict with ``max_abs_diff``, ``passed``, ``n``, and ``tolerance``.
    Raises AssertionError if the difference exceeds ``atol`` (so the pipeline
    surfaces a real portability regression).
    """
    import onnxruntime as ort

    onnx_path = Path(onnx_path) if onnx_path else artifacts_dir(out) / ONNX_FILE
    codes = encode_codes(sample, model.categories)

    native = _native_proba_from_codes(model, codes)

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {input_name: codes})
    onnx_proba = _extract_positive_proba(outputs, n=len(sample))

    max_abs_diff = float(np.max(np.abs(native - onnx_proba)))
    passed = max_abs_diff <= atol
    result = {
        "n": int(len(sample)),
        "tolerance": atol,
        "max_abs_diff": max_abs_diff,
        "passed": bool(passed),
    }
    assert passed, (
        f"ONNX portability test FAILED: max_abs_diff={max_abs_diff:.2e} > atol={atol:.0e}"
    )
    return result


def _extract_positive_proba(outputs: list, n: int) -> np.ndarray:
    """Pull P(class=1) out of onnxruntime outputs (handles label+proba layouts)."""
    # onnxmltools lgbm classifier (zipmap=False) returns [labels, probabilities]
    for arr in outputs:
        a = np.asarray(arr)
        if a.ndim == 2 and a.shape[0] == n and a.shape[1] == 2:
            return a[:, 1].astype("float64")
        if a.ndim == 2 and a.shape[0] == n and a.shape[1] == 1:
            return a[:, 0].astype("float64")
    # fallback: last output flattened
    return np.asarray(outputs[-1]).reshape(n, -1)[:, -1].astype("float64")
