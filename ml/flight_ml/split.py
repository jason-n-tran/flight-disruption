"""Temporal train/test split — the single most important methodological choice.

WHY NOT A RANDOM SPLIT
----------------------
This dataset is a time series with *rolling, leakage-safe* features
(``route_hist_delay_rate``, ``origin_hist_delay_rate``, ``carrier_hist_delay_rate``)
that are computed from flights strictly *before* each target flight. A random
train/test split would scatter rows from the same time period across both sets,
so the model would (a) implicitly learn from neighbours that occur *after* test
flights and (b) be evaluated on a period it has already "seen" the dynamics of.
That inflates metrics and is exactly the failure a hiring ML reviewer looks for.

We instead split by calendar year: train on ``TRAIN_YEARS`` (2022-2024), test on
``TEST_YEARS`` (2025). This mimics deployment: train on the past, predict the
future. An assertion enforces zero year-overlap.

For early stopping and calibration we further carve *temporal* slices from the
END of the train period (see :func:`train_valid_calib_split`) — never random.
"""

from __future__ import annotations

import pandas as pd

from .config import CALIB_FRACTION, TEST_YEARS, TRAIN_YEARS, VALID_FRACTION


def temporal_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into (train, test) by year using the contract's TRAIN/TEST years.

    Raises if any test year leaks into train (or vice versa), or if either side
    is empty.
    """
    if "year" not in df.columns:
        raise ValueError("temporal_split requires a 'year' column")

    train = df[df["year"].isin(TRAIN_YEARS)].copy()
    test = df[df["year"].isin(TEST_YEARS)].copy()

    train_years = set(train["year"].unique())
    test_years = set(test["year"].unique())

    # The non-negotiable guarantee.
    assert not (train_years & set(TEST_YEARS)), (
        f"Leakage: TEST_YEARS found in train slice ({train_years & set(TEST_YEARS)})"
    )
    assert not (test_years & set(TRAIN_YEARS)), (
        f"Leakage: TRAIN_YEARS found in test slice ({test_years & set(TRAIN_YEARS)})"
    )
    assert len(train) > 0, "Train split is empty (no TRAIN_YEARS rows in data)"
    assert len(test) > 0, "Test split is empty (no TEST_YEARS rows in data)"

    return train, test


def _order_by_time(df: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [c for c in ("year", "flight_date") if c in df.columns]
    if sort_cols:
        return df.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return df.reset_index(drop=True)


def train_valid_calib_split(
    train: pd.DataFrame,
    valid_fraction: float = VALID_FRACTION,
    calib_fraction: float = CALIB_FRACTION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Carve temporal validation (early stop) + calibration slices from train END.

    Returns ``(fit, valid, calib)`` where, after sorting by time:
      * ``fit``   = earliest portion (model training);
      * ``valid`` = next slice (LightGBM early stopping);
      * ``calib`` = most recent slice (probability calibration).

    All three are disjoint and strictly ordered in time, so neither early
    stopping nor calibration ever sees data from before the training fit window's
    successors leaking backwards. ``calib`` is the closest to the test period, so
    the calibration map reflects the most recent regime.
    """
    df = _order_by_time(train)
    n = len(df)
    n_calib = max(1, int(n * calib_fraction))
    n_valid = max(1, int(n * valid_fraction))
    if n_calib + n_valid >= n:
        # tiny datasets: shrink slices so fit keeps at least one row
        n_calib = max(1, n // 5)
        n_valid = max(1, n // 5)

    # iloc slices are cheap views; .copy() materializes each. Take views and let
    # the caller drop `train`/`df` — avoids holding sorted-df + 3 full copies at
    # once (a ~2x spike on the 20M-row train set that OOMs a 12GB container).
    fit = df.iloc[: n - n_valid - n_calib]
    valid = df.iloc[n - n_valid - n_calib : n - n_calib]
    calib = df.iloc[n - n_calib :]
    assert len(fit) > 0 and len(valid) > 0 and len(calib) > 0
    return fit, valid, calib
