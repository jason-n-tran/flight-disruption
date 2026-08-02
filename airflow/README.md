# Airflow Orchestration (Working-PC Showcase)

Production-grade orchestration of the Flight Disruption Platform's **batch + ML
lifecycle**. This is a **showcase component** (see the repo `CLAUDE.md`
"showcase pattern"): it runs on the maintainer's **Working PC and is NOT
always-on**, and **the live demo never depends on it**. The DAGs are real and
runnable — a reviewer can read them and trigger them. Screenshots of the DAG
graph + a green run go in `docs/` for the portfolio.

## DAGs

### `flight_batch_pipeline` (`@weekly`, catchup off)
The main end-to-end refresh of the batch "brain" track:

```
start
  └─ [ingest]  airports ─▶ bts ─▶ weather        (TaskGroup; bronze)
        └─ lakehouse_silver ─▶ lakehouse_gold     (PySpark: bronze→silver→gold)
              └─ dbt_run ─▶ dbt_test              (gold marts in DuckDB, tested)
                    └─ ml_train                    (temporal split, calibrate, SHAP, MLflow, ONNX)
                          └─ publish_artifacts ─▶ end   (upload bundle + gold.duckdb; no-op if S3 unset)
```
Retries=2 with exponential backoff, `max_active_runs=1`, tagged
`flight/batch/ml/showcase`. The ingest `years` are a DAG **param** (defaults to
the `flight_train_years` Variable) so you can trigger-with-config.

### `flight_model_retrain` (`@monthly`, catchup off)
The retraining lifecycle with a **model-quality gate**:

```
start ─▶ rebuild_features (gold) ─▶ train_and_evaluate ─▶ quality_gate (BranchPythonOperator)
                                                              ├─ PASS ─▶ gate_passed_publish ─▶ mlflow_register ─▶ snapshot_metrics ─┐
                                                              └─ FAIL ─▶ gate_failed_skip ──────────────────────────────────────────┴─▶ join
```
The gate reads `ml/reports/metrics.json` and publishes **only if** the new
`model_roc_auc` clears both the absolute floor (`flight_roc_auc_gate` Variable,
default 0.55) **and** the previous model's ROC-AUC (snapshotted to
`ml/reports/metrics_previous.json` after each successful publish). MLflow
registration happens via `flight_ml.registry` when `MLFLOW_*` env is set.

### `flight_weather_backfill` (manual, `schedule=None`)
A utility that backfills the Open-Meteo archive for all airports, showing a
**different pattern**: manual trigger + **dynamic task mapping** (one mapped
ingest task per year, fan-out with per-year retries).

## How it works

DAGs call the real component CLIs via `BashOperator` (and `PythonOperator` for
the gate logic):

| Step       | Command                                                       |
|------------|--------------------------------------------------------------|
| ingest     | `python -m flight_ingest.cli {airports\|bts\|weather}`       |
| lakehouse  | `python -m flight_lakehouse.run --stage {silver\|gold}`      |
| dbt        | `python -m dbt.cli.main {run\|test}` (in `dbt/flight/`)      |
| ml         | `python -m flight_ml.pipeline --data <gold.duckdb> --out ml/artifacts` |
| publish    | `python airflow/scripts/publish_artifacts.py`                |

No maintainer-specific paths are hardcoded. All knobs are **Airflow Variables**
with sensible relative defaults anchored at the repo root (derived from the DAG
file location). See `dags/_config.py`.

### Variables (Admin → Variables, all optional)
| Variable | Default | Purpose |
|----------|---------|---------|
| `flight_repo_root` | derived (`airflow/dags/../..`) | monorepo root |
| `flight_lake_root` | `<repo>/data/lake` | `LAKE_ROOT` |
| `flight_duckdb_path` | `<lake>/gold.duckdb` | gold DuckDB |
| `flight_train_years` | `2022,2023,2024,2025` | ingest/train/backfill years |
| `flight_python` | the worker's `sys.executable` | python to invoke |
| `flight_roc_auc_gate` | `0.55` | retrain publish floor |

## Run it locally

**Dependency note:** the orchestrated components must be importable on the same
environment the Airflow workers run in. Either `pip install -e` each sub-project
(`ingestion/`, `lakehouse/`, `ml/`, `shared/`, `dbt-duckdb`) or ensure
`PYTHONPATH` includes `shared/` (the DAGs already export it for `flight_contracts`).

### Option A — `airflow standalone` (no Docker)
```bash
python -m venv .venv && source .venv/bin/activate     # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.4/constraints-3.12.txt"
# install the components so the CLIs import:
pip install -e ../shared -e ../ingestion -e ../lakehouse -e ../ml dbt-duckdb

export AIRFLOW_HOME="$PWD/.airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
airflow standalone        # prints the admin password; UI at http://localhost:8080
```

### Option B — Docker (single-container standalone)
```bash
cp .env.example .env
docker compose -f docker-compose.airflow.yml up
# UI: http://localhost:8080  (login in the logs: admin / <generated>)
```
The compose mounts the whole monorepo at `/opt/flight`. The image still needs
the component packages installed to *run* tasks; for screenshots of the DAG
graph / structure that isn't required.

## Validate DAG parsing
```bash
python -c "from airflow.models import DagBag; db=DagBag('dags', include_examples=False); assert not db.import_errors, db.import_errors; print('DAGs OK:', list(db.dags))"
```

## Files
```
airflow/
├── dags/
│   ├── _config.py                  # Variables/env-driven config + command builders
│   ├── flight_batch_pipeline.py    # @weekly ingest→lakehouse→dbt→ml→publish
│   ├── flight_model_retrain.py     # @monthly retrain + ROC-AUC quality gate
│   └── flight_weather_backfill.py  # manual, dynamic-mapped weather backfill
├── scripts/
│   └── publish_artifacts.py        # uploads bundle + gold.duckdb to S3/MinIO (no-op if blank)
├── requirements.txt
├── docker-compose.airflow.yml
├── .env.example
└── README.md
```
