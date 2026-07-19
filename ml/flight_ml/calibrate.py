"""Probability calibration so ``delay_probability`` is honest.

A LightGBM score that ranks well (good AUC) can still be poorly *calibrated* —
e.g. it says 0.8 when the empirical rate is 0.5. Since the API surfaces a
probability (and risk bands keyed on it), calibration matters as much as ranking.

We fit a calibration map on a held-out *temporal* slice (the most recent portion
of train, closest to the test regime — see :func:`flight_ml.split.train_valid_calib_split`)
and report the Brier score before/after. Isotonic is the default (flexible,
monotone); Platt (sigmoid) is available for very small calibration sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

Method = Literal["isotonic", "sigmoid"]


@dataclass
class Calibrator:
    method: Method
    _isotonic: IsotonicRegression | None = None
    _platt: LogisticRegression | None = None
    brier_before: float = float("nan")
    brier_after: float = float("nan")

    def transform(self, raw_proba: np.ndarray) -> np.ndarray:
        raw = np.asarray(raw_proba, dtype="float64")
        if self.method == "isotonic":
            assert self._isotonic is not None
            return np.clip(self._isotonic.predict(raw), 0.0, 1.0)
        assert self._platt is not None
        return self._platt.predict_proba(raw.reshape(-1, 1))[:, 1]


def fit_calibrator(
    raw_proba: np.ndarray,
    y_true: np.ndarray,
    method: Method = "isotonic",
) -> Calibrator:
    """Fit a calibrator on (uncalibrated proba, label) from the temporal calib slice."""
    raw = np.asarray(raw_proba, dtype="float64")
    y = np.asarray(y_true, dtype="int")
    brier_before = float(brier_score_loss(y, raw))

    cal = Calibrator(method=method)
    if method == "isotonic":
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(raw, y)
        cal._isotonic = iso
    else:
        lr = LogisticRegression(max_iter=1000)
        lr.fit(raw.reshape(-1, 1), y)
        cal._platt = lr

    cal.brier_before = brier_before
    cal.brier_after = float(brier_score_loss(y, cal.transform(raw)))
    return cal
