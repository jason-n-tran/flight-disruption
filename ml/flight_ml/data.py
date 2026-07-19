"""Data access: load the real gold feature table, or generate synthetic data.

The real gold table (``gold/fct_flight_features``, parquet partitioned by year)
is produced by the lakehouse component and won't exist in dev/CI. So:

* :func:`load_features` reads it when present (parquet dir or a DuckDB file);
* :func:`make_synthetic` builds a dataframe with the EXACT contract schema and a
  *learnable* signal, so the whole pipeline (and the tests) run offline.

Both return a single pandas dataframe with columns ==
``MODEL_FEATURES + [LABEL_COLUMN] + IDENTITY_COLUMNS``. Categorical features are
left as plain object/int here; :func:`coerce_dtypes` applies the ``category``
dtype just before training/scoring (so the same coercion is used everywhere).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    CATEGORICAL_FEATURES,
    IDENTITY_COLUMNS,
    LABEL_COLUMN,
    MODEL_FEATURES,
    NUMERIC_FEATURES,
    TEST_YEARS,
    TRAIN_YEARS,
)

# A small but realistic airport/carrier vocabulary for synthetic data.
_AIRPORTS = ["ATL", "ORD", "DFW", "DEN", "LAX", "JFK", "EWR", "SFO", "SEA", "LAS"]
_CARRIERS = ["DL", "AA", "UA", "WN", "B6", "AS"]
_TOD_BUCKETS = ["night", "morning", "afternoon", "evening"]


def _time_of_day_bucket(dep_hour: np.ndarray) -> np.ndarray:
    out = np.empty(dep_hour.shape, dtype=object)
    out[(dep_hour < 6)] = "night"
    out[(dep_hour >= 6) & (dep_hour < 12)] = "morning"
    out[(dep_hour >= 12) & (dep_hour < 18)] = "afternoon"
    out[(dep_hour >= 18)] = "evening"
    return out


def make_synthetic(
    n_per_year: int = 4000,
    years: list[int] | None = None,
    seed: int = 17,
) -> pd.DataFrame:
    """Generate a contract-schema dataframe with a learnable delay signal.

    The label ``dep_del15`` is driven by a logistic function of (mainly)
    ``origin_wind_gusts`` and ``dep_hour`` (evening rush + gusty wind => more
    delays), plus weaker route/carrier history effects and noise. This gives the
    model real signal to beat the base-rate baseline, while keeping per-route
    base rates non-trivial so the baseline isn't a strawman.
    """
    years = years or (TRAIN_YEARS + TEST_YEARS)
    rng = np.random.default_rng(seed)
    frames = []

    for year in years:
        n = n_per_year
        origin = rng.choice(_AIRPORTS, n)
        dest = rng.choice(_AIRPORTS, n)
        # avoid origin == dest
        same = origin == dest
        dest[same] = rng.choice(_AIRPORTS, same.sum())
        carrier = rng.choice(_CARRIERS, n)

        month = rng.integers(1, 13, n)
        day_of_month = rng.integers(1, 28, n)
        day_of_week = rng.integers(1, 8, n)
        dep_hour = rng.integers(0, 24, n)
        tod = _time_of_day_bucket(dep_hour)

        distance = rng.uniform(150, 2800, n).round(0)
        crs_elapsed = (distance / 7.0 + rng.normal(40, 10, n)).clip(35, 400).round(0)
        is_holiday = (rng.random(n) < 0.06).astype(int)

        # Per-airport / per-carrier latent "badness" -> stable historical rates.
        airport_bad = {a: rng.uniform(0.10, 0.30) for a in _AIRPORTS}
        carrier_bad = {c: rng.uniform(0.12, 0.26) for c in _CARRIERS}
        origin_hist = np.array([airport_bad[a] for a in origin])
        route_hist = (origin_hist + np.array([airport_bad[d] for d in dest])) / 2.0
        carrier_hist = np.array([carrier_bad[c] for c in carrier])

        # Weather. Wind gusts at origin is the dominant driver.
        origin_temp = rng.normal(15, 12, n).round(1)
        origin_precip = rng.gamma(0.5, 1.5, n).round(2)
        origin_wind = rng.gamma(2.0, 4.0, n).round(1)
        origin_gusts = (origin_wind + rng.gamma(2.0, 6.0, n)).round(1)
        origin_snow = (rng.gamma(0.3, 1.0, n) * (origin_temp < 2)).round(2)

        dest_temp = rng.normal(15, 12, n).round(1)
        dest_precip = rng.gamma(0.5, 1.5, n).round(2)
        dest_wind = rng.gamma(2.0, 4.0, n).round(1)
        dest_gusts = (dest_wind + rng.gamma(2.0, 6.0, n)).round(1)
        dest_snow = (rng.gamma(0.3, 1.0, n) * (dest_temp < 2)).round(2)

        # ----- the signal -----
        evening_rush = ((dep_hour >= 16) & (dep_hour <= 20)).astype(float)
        logit = (
            -1.9
            + 0.045 * origin_gusts
            + 0.9 * evening_rush
            + 0.02 * origin_precip
            + 2.5 * (route_hist - 0.2)
            + 1.5 * (carrier_hist - 0.2)
            + 0.6 * origin_snow
            + 0.4 * is_holiday
            + rng.normal(0, 0.6, n)
        )
        prob = 1.0 / (1.0 + np.exp(-logit))
        label = (rng.random(n) < prob).astype(int)

        flight_date = pd.to_datetime(
            dict(year=year, month=month, day=day_of_month)
        )

        df = pd.DataFrame(
            {
                # categorical
                "origin": origin,
                "dest": dest,
                "carrier": carrier,
                "dep_hour": dep_hour,
                "day_of_week": day_of_week,
                "month": month,
                "time_of_day_bucket": tod,
                # numeric
                "distance": distance,
                "crs_elapsed_time": crs_elapsed,
                "is_holiday_window": is_holiday,
                "route_hist_delay_rate": route_hist.round(4),
                "origin_hist_delay_rate": origin_hist.round(4),
                "carrier_hist_delay_rate": carrier_hist.round(4),
                "origin_temp_2m": origin_temp,
                "origin_precip": origin_precip,
                "origin_wind_speed": origin_wind,
                "origin_wind_gusts": origin_gusts,
                "origin_snowfall": origin_snow,
                "dest_temp_2m": dest_temp,
                "dest_precip": dest_precip,
                "dest_wind_speed": dest_wind,
                "dest_wind_gusts": dest_gusts,
                "dest_snowfall": dest_snow,
                # label + identity
                LABEL_COLUMN: label,
                "flight_date": flight_date,
                "year": year,
                "_origin_id": origin,  # placeholder, dropped; identity below
            }
        )
        df = df.drop(columns=["_origin_id"])
        frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    # column order: model features, label, identity
    ordered = MODEL_FEATURES + [LABEL_COLUMN] + ["flight_date", "year"]
    out = out[ordered]
    return out


def coerce_dtypes(
    df: pd.DataFrame,
    categories: dict[str, list] | None = None,
) -> pd.DataFrame:
    """Apply pandas ``category`` dtype to categorical features and floats to numerics.

    ``categories`` pins the categorical level sets (from training) so that test /
    serving rows encode to the SAME integer codes — essential for LightGBM native
    categorical handling and for ONNX consistency. Unseen levels become NaN code.
    """
    # Shallow copy (no deep data copy): shares the underlying column arrays, so
    # reassigning a column swaps that column's reference without duplicating the
    # whole ~27M-row frame (a deep copy was a contributor to the OOM SIGKILL).
    # Callers' frames are left untouched (predict_proba runs on raw test rows).
    df = df.copy(deep=False)
    for col in CATEGORICAL_FEATURES:
        if col not in df.columns:
            continue
        if categories is not None and col in categories:
            dtype = pd.CategoricalDtype(categories=categories[col])
            df[col] = df[col].astype(dtype)
        else:
            df[col] = df[col].astype("category")
    for col in NUMERIC_FEATURES:
        if col in df.columns:
            # float32 (not 64): halves numeric memory; LightGBM bins to float
            # internally anyway, so no meaningful precision loss for these feats.
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    return df


def extract_categories(df: pd.DataFrame) -> dict[str, list]:
    """Return the sorted level set for each categorical feature (for metadata)."""
    cats: dict[str, list] = {}
    for col in CATEGORICAL_FEATURES:
        if col not in df.columns:
            continue
        vals = pd.Series(df[col]).dropna().unique().tolist()
        # normalise to JSON-safe python scalars
        norm = [int(v) if isinstance(v, (np.integer,)) else v for v in vals]
        norm = sorted(norm, key=lambda x: (str(type(x)), x))
        cats[col] = norm
    return cats


def load_features(data: str | os.PathLike) -> pd.DataFrame:
    """Load the gold feature table from a parquet directory or a DuckDB file.

    * If ``data`` is a directory or ``.parquet`` glob -> read parquet (the lake).
    * If ``data`` ends in ``.duckdb``/``.db`` -> query ``GOLD_FEATURES_TABLE``.

    Returns columns in the canonical (model features, label, identity) order when
    available; missing identity columns are tolerated (only year + label are
    strictly required for the pipeline).
    """
    path = Path(data)
    # De-dup while preserving order: origin/dest appear in BOTH MODEL_FEATURES
    # and IDENTITY_COLUMNS; selecting them twice yields duplicate DataFrame cols.
    want = list(dict.fromkeys(MODEL_FEATURES + [LABEL_COLUMN] + IDENTITY_COLUMNS))
    if str(path).endswith((".duckdb", ".db")):
        import duckdb  # local import: optional in some contexts

        from .config import GOLD_FEATURES_TABLE

        con = duckdb.connect(str(path), read_only=True)
        try:
            # Cap DuckDB's own working memory so it doesn't compete with pandas
            # for the (often WSL2-limited) container RAM. Env-overridable.
            mem_limit = os.environ.get("DUCKDB_MEMORY_LIMIT", "2GB")
            try:
                con.execute(f"PRAGMA memory_limit='{mem_limit}'")
                con.execute("PRAGMA threads=2")
            except Exception:  # noqa: BLE001 — pragmas are best-effort
                pass
            # Project only the needed columns IN DuckDB (not SELECT *): with
            # ~27M rows, pulling unused columns would balloon memory.
            available = {
                r[0] for r in con.execute(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name = '{GOLD_FEATURES_TABLE}'"
                ).fetchall()
            }
            cols = [c for c in want if c in available]
            _check_required(available)
            collist = ", ".join(f'"{c}"' for c in cols)
            # Go via Arrow and map dtypes on the way into pandas: string cols ->
            # category (origin/dest/carrier over 27M rows as object strings are
            # the big memory spike), and Arrow buffers are shared, not re-copied.
            tbl = con.execute(
                f"SELECT {collist} FROM {GOLD_FEATURES_TABLE}"
            ).fetch_arrow_table()
        finally:
            con.close()
        # strings_to_categorical: origin/dest/carrier as category instead of
        # fat object arrays (the big spike at ~27M rows). split_blocks +
        # self_destruct free Arrow buffers as they convert, halving peak.
        df = tbl.to_pandas(
            strings_to_categorical=True,
            split_blocks=True,
            self_destruct=True,
        )
        del tbl
        return df

    # parquet: either a directory partitioned by year, or a single file. Project
    # columns at read time so we never materialize unused ones.
    import pyarrow.parquet as pq

    schema_names = set(pq.ParquetDataset(path).schema.names) if path.is_dir() else \
        set(pq.read_schema(path).names)
    _check_required(schema_names)
    cols = [c for c in want if c in schema_names]
    df = pd.read_parquet(path, columns=cols)
    return df
