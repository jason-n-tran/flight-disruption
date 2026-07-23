# flight_ml — Flight Delay Risk Model

The **machine-learning brain** of the Flight Disruption Intelligence Platform. It
turns the gold per-flight feature table into an explainable, calibrated
delay-risk model — and, just as importantly, it does so with the methodological
discipline a machine-learning reviewer actually checks for.

This README is itself a portfolio artifact: it states the ML judgment up front.

---

## The ML judgment (read this first)

> A delay model that looks good on a random split and isn't calibrated is worse
> than useless — it lies confidently about the future. Everything below exists to
> avoid that.

| Decision | What we did | Why it matters |
|---|---|---|
| **Temporal split, never random** | Train = 2022-24, test = 2025 (`split.py`). | The data is a time series with *rolling* history features. A random split leaks the future into the past and inflates every metric. The split asserts zero year-overlap. |
| **A real baseline to beat** | Per-route historical delay rate, fit on train only, global-mean fallback for unseen routes (`baseline.py`). | "Did we beat predicting the route's base rate?" is the only honest bar. It's also the API's `baseline_probability`. |
| **Native categorical handling** | `origin/dest/carrier/dep_hour/...` passed as `categorical_feature` to LightGBM (`train.py`). | No one-hot blow-up; LightGBM splits on optimal category subsets. |
| **Class imbalance handled** | `scale_pos_weight = #neg/#pos`. | Delays are the minority class; otherwise the model collapses to "never delayed". |
| **Temporal early stopping** | Validation slice carved from the *end* of the train period, not a random fold. | Consistent with the no-leakage rule. |
| **Probability calibration** | Isotonic calibration on a held-out temporal slice; Brier reported before/after (`calibrate.py`). | The API returns a *probability*. Good ranking (AUC) ≠ honest probabilities. |
| **Honest evaluation** | ROC-AUC, **PR-AUC** (the one that matters under imbalance), Brier, calibration curve, and an explicit model-vs-baseline lift line (`evaluate.py`). | A single "model beats baseline by X" line, plus `reports/metrics.json` and a calibration PNG. |
| **Live, signed explanations** | SHAP `TreeExplainer` on the native model → `top_factors` (`explain.py`). | Powers the API's per-prediction explanation, computed live in serving. |
| **MLOps showcases** | MLflow tracking/registry (`registry.py`), ONNX export + portability test (`export_onnx.py`). | Reproducibility + "runs anywhere onnxruntime runs". ONNX is a *showcase*; serving uses the native model so SHAP works. |

---

## Quickstart

```bash
# from ml/
pip install -e ../shared -e .          # pulls lightgbm/shap/mlflow/onnx (sizable)
python -m pytest -q                     # offline, synthetic data
python -m flight_ml.pipeline --synthetic --out artifacts   # full run, no real lake
```

Against the real gold table (parquet dir partitioned by year, or a DuckDB file):

```bash
python -m flight_ml.pipeline --data ../data/lake/gold/fct_flight_features --out artifacts
python -m flight_ml.pipeline --data gold.duckdb --out artifacts   # reads fct_flight_features
```

The pipeline runs **split → train → calibrate → evaluate → explain → mlflow →
onnx → bundle** and is deterministic.

---

## What it produces

`artifacts/` (consumed by the serving layer + the sample-artifact generator):

- `model.lgb` — native LightGBM booster (used for scoring **and** live SHAP).
- `calibrator.pkl` — the fitted probability calibrator.
- `feature_metadata.json` — feature order, categorical levels + integer codes,
  dtypes, the baseline route table + global prior, model metadata.
- `model.onnx` — portable model (showcase; verified against native within 1e-4).

`reports/`:

- `metrics.json` — all metrics + the model-vs-baseline lift.
- `calibration_curve.png` / `.json` — reliability curve on the test set.

`mlruns/` — local MLflow file store (no server needed) with params, metrics, the
logged model, and artifacts.

---

## The serving contract

The serving layer imports one function — the single source of truth for "how to
score a flight":

```python
from flight_ml.artifacts import load_bundle, predict_proba_one

art = load_bundle("artifacts")          # loads model + calibrator + metadata + baseline
result = predict_proba_one(art, {       # all keys are MODEL_FEATURES (pre-departure safe)
    "origin": "ATL", "dest": "ORD", "carrier": "DL", "dep_hour": 17,
    "day_of_week": 5, "month": 6, "time_of_day_bucket": "afternoon",
    "distance": 606, "crs_elapsed_time": 125, "is_holiday_window": 0,
    "route_hist_delay_rate": 0.22, "origin_hist_delay_rate": 0.21,
    "carrier_hist_delay_rate": 0.19, "origin_temp_2m": 22, "origin_precip": 0,
    "origin_wind_speed": 18, "origin_wind_gusts": 41.2, "origin_snowfall": 0,
    "dest_temp_2m": 18, "dest_precip": 1.2, "dest_wind_speed": 12,
    "dest_wind_gusts": 22.0, "dest_snowfall": 0,
})
# -> {delay_probability, risk_band, baseline_probability, beats_baseline,
#     calibrated, top_factors:[{feature,value,contribution,direction}, ...]}
```

This is exactly the shape of `POST /api/predict` in
`shared/flight_contracts/api_contract.md`.

---

## Honesty / limitations

- Predicts **probability**, never a guarantee. Risk bands: low `<0.20`,
  moderate `0.20-0.45`, high `≥0.45`.
- Weather at train time is *observed-as-proxy* for the forecast that would be
  available at serve time (documented in the project's data contract).
- The model uses **only pre-departure-known features** — the leakage contract in
  `shared/flight_contracts/contract.py` is enforced upstream and mirrored here.

## Configuration

See `.env.example`. `MLFLOW_TRACKING_URI` defaults to a local file store
(`./mlruns`) if unset — training never requires a running MLflow server.
