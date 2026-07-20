"""End-to-end ML pipeline: split -> train -> calibrate -> evaluate -> explain
-> mlflow -> onnx -> bundle.

Usage::

    python -m flight_ml.pipeline --data <parquet_dir|file.duckdb> --out ml/artifacts
    python -m flight_ml.pipeline --synthetic --out ml/artifacts

``--synthetic`` runs the whole thing on generated contract-schema data (for
smoke tests / demos without the real lake). Everything is deterministic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

import numpy as np
import pandas as pd

from .artifacts import load_bundle, predict_proba_one, save_bundle
from .baseline import BaseRateBaseline
from .calibrate import fit_calibrator
from .config import (
    CATEGORICAL_FEATURES,
    LABEL_COLUMN,
    MODEL_FEATURES,
    artifacts_dir,
    reports_dir,
)
from .data import extract_categories, load_features, make_synthetic
from .evaluate import evaluate, format_summary
from .explain import build_explainer, top_factors
from .export_onnx import export_onnx, portability_test
from .registry import tracking_run
from .split import temporal_split, train_valid_calib_split
from .train import train_model


def run_pipeline(
    df: pd.DataFrame,
    out: str | None = None,
    do_onnx: bool = True,
    do_mlflow: bool = True,
    calibration_method: str = "isotonic",
) -> dict:
    """Run the full pipeline on an in-memory dataframe. Returns a summary dict."""
    print(f"[pipeline] rows={len(df):,} features={len(MODEL_FEATURES)}")

    # 1) temporal split. Free the parent frame immediately: at ~27M rows keeping
    # df + train + test alive at once is ~2x the data and OOMs a 12GB container.
    import gc

    train, test = temporal_split(df)
    del df
    gc.collect()
    n_train, n_test = len(train), len(test)  # capture before `train` is freed
    print(f"[split] train={n_train:,} (yrs {sorted(train['year'].unique())}) "
          f"test={n_test:,} (yrs {sorted(test['year'].unique())})")

    # category levels pinned from the FULL train set (stable encodings everywhere)
    categories = extract_categories(train)

    # 2) baseline (fit on train only)
    baseline = BaseRateBaseline().fit(train)
    base_test = baseline.predict_proba(test)
    print(f"[baseline] global_prior={baseline.global_prior:.4f} "
          f"routes={len(baseline.route_rates)}")

    # 3) temporal fit/valid/calib slices, then train. Drop `train` once sliced —
    # fit/valid/calib are the only views needed from here, and the LightGBM
    # Dataset below is another large allocation.
    fit_df, valid_df, calib_df = train_valid_calib_split(train)
    del train
    gc.collect()
    print(f"[temporal-slices] fit={len(fit_df):,} valid={len(valid_df):,} "
          f"calib={len(calib_df):,}")
    model = train_model(fit_df, valid_df, categories)
    print(f"[train] best_iteration={model.best_iteration} "
          f"scale_pos_weight={model.scale_pos_weight:.3f}")

    # 4) calibration on the held-out temporal calib slice
    calib_raw = model.predict_proba(calib_df)
    calibrator = fit_calibrator(
        calib_raw, calib_df[LABEL_COLUMN].to_numpy(), method=calibration_method
    )
    print(f"[calibrate] method={calibrator.method} "
          f"Brier {calibrator.brier_before:.4f} -> {calibrator.brier_after:.4f}")

    # 5) evaluate on test
    model_raw_test = model.predict_proba(test)
    model_cal_test = calibrator.transform(model_raw_test)
    metrics = evaluate(
        y_test=test[LABEL_COLUMN].to_numpy(),
        model_raw=model_raw_test,
        model_calibrated=model_cal_test,
        baseline_proba=base_test,
        calib_brier_before=calibrator.brier_before,
        calib_brier_after=calibrator.brier_after,
        out=reports_dir(),
    )
    print("[evaluate] " + format_summary(metrics))

    # 6) explainability smoke (SHAP on one row)
    explainer = build_explainer(model)
    sample_row = test.iloc[[0]][MODEL_FEATURES]
    factors = top_factors(explainer, sample_row, k=3)
    print(f"[explain] top_factors sample: "
          f"{[(f['feature'], f['direction']) for f in factors]}")

    # 9) bundle artifacts (do this before onnx so artifacts dir exists)
    adir = save_bundle(model, calibrator, baseline, out=out)
    print(f"[artifacts] wrote bundle -> {adir}")

    # 8) ONNX export + portability test (showcase)
    onnx_result = None
    if do_onnx:
        try:
            onnx_path = export_onnx(model, out=out)
            onnx_result = portability_test(
                model, test.iloc[:200][MODEL_FEATURES], onnx_path=onnx_path, out=out
            )
            print(f"[onnx] exported -> {onnx_path} | portability "
                  f"max_abs_diff={onnx_result['max_abs_diff']:.2e} "
                  f"passed={onnx_result['passed']}")
        except Exception as exc:
            onnx_result = {"passed": False, "error": str(exc)}
            print(f"[onnx] FAILED: {exc}")

    # 7) MLflow tracking
    if do_mlflow:
        with tracking_run(run_name="flight_delay_pipeline",
                          tags={"split": "temporal", "model": "lightgbm"}) as run:
            run.log_params({
                "n_train": n_train, "n_test": n_test,
                "best_iteration": model.best_iteration,
                "scale_pos_weight": model.scale_pos_weight,
                "calibration_method": calibrator.method,
                "n_features": len(MODEL_FEATURES),
            })
            run.log_metrics(asdict(metrics))
            run.log_lightgbm(model.booster)
            run.log_artifacts(str(adir))
            run.log_artifacts(str(reports_dir()))
        print("[mlflow] logged run (local file store unless MLFLOW_TRACKING_URI set)")

    # verify the reference scoring path round-trips from disk
    loaded = load_bundle(out)
    one = predict_proba_one(loaded, test.iloc[0][MODEL_FEATURES].to_dict())
    print(f"[serving-check] predict_proba_one -> prob={one['delay_probability']:.4f} "
          f"band={one['risk_band']} factors={len(one['top_factors'])}")

    return {
        "metrics": asdict(metrics),
        "onnx": onnx_result,
        "artifacts_dir": str(adir),
        "sample_prediction": one,
    }


def load_input(args) -> pd.DataFrame:
    if args.synthetic or not args.data:
        n = args.synthetic_rows
        print(f"[data] generating synthetic dataset ({n} rows/year)")
        return make_synthetic(n_per_year=n)
    print(f"[data] loading gold feature table from {args.data}")
    return load_features(args.data)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Flight delay ML training pipeline.")
    p.add_argument("--data", help="parquet dir/file or .duckdb path (gold fct_flight_features)")
    p.add_argument("--out", default=None, help="artifacts output dir (default ml/artifacts)")
    p.add_argument("--synthetic", action="store_true", help="run on generated data")
    p.add_argument("--synthetic-rows", type=int, default=4000, help="rows/year for synthetic")
    p.add_argument("--no-onnx", action="store_true", help="skip ONNX export/portability")
    p.add_argument("--no-mlflow", action="store_true", help="skip MLflow tracking")
    p.add_argument("--calibration", default="isotonic", choices=["isotonic", "sigmoid"])
    return p
