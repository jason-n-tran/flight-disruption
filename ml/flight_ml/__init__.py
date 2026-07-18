"""flight_ml — the ML training pipeline for the Flight Disruption Platform.

The whole point of this package is *credible ML judgment*, not just a model:

* temporal (not random) train/test split — rolling features + time series make a
  random split leak the future into the past (see ``split``);
* a real base-rate baseline the model must beat (``baseline``);
* probability calibration so ``delay_probability`` is honest (``calibrate``);
* ROC-AUC / PR-AUC / Brier + a calibration curve, model-vs-baseline (``evaluate``);
* live, signed SHAP attributions for the API's ``top_factors`` (``explain``);
* MLflow tracking (``registry``), ONNX export + portability test (``export_onnx``);
* a self-describing artifact bundle the serving layer consumes (``artifacts``).

``predict_proba_one`` (in ``artifacts``) is the single reference scoring function
shared by serving and the tests.
"""

from __future__ import annotations

__all__ = [
    "__version__",
]

__version__ = "0.1.0"
