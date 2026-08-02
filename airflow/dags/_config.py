"""Shared config + helpers for the Flight Disruption Platform DAGs.

Design goal: **no Airflow metadata-DB access at DAG parse time**. The scheduler
re-parses DAG files constantly, so reading Variables at module top level is both
slow and fragile (it errors before ``airflow db init``). Instead we:

* compute path defaults from the DAG file location (a pure-Python anchor), and
* resolve runtime knobs (Variables) via **Jinja templates** in the bash
  commands, which Airflow renders at task-execution time (``{{ var.value.get(...) }}``).

So every command string below is a *template*; the actual Variable lookups (with
defaults) happen when a task runs, not when the file is parsed.

Variables (override in the Airflow UI -> Admin -> Variables; all optional):
    flight_repo_root      : abs path to repo root      (default: derived)
    flight_lake_root      : LAKE_ROOT for the lakehouse (default: <repo>/data/lake)
    flight_duckdb_path    : gold DuckDB path            (default: <lake>/gold.duckdb)
    flight_train_years    : comma list for ingest/train (default: 2022,2023,2024,2025)
    flight_python         : python executable            (default: "python")
    flight_roc_auc_gate   : min ROC-AUC to publish       (default: 0.55) -- read in the
                            retrain gate's PythonOperator (runtime), not here.
"""

from __future__ import annotations

import os
from pathlib import Path

# airflow/dags/_config.py -> parents[2] == repo root. Pure path math, no DB.
DERIVED_REPO_ROOT = str(Path(__file__).resolve().parents[2])

# --------------------------------------------------------------------------- #
# Jinja fragments -- resolved at task runtime by Airflow's template engine.
# `var.value.get('k', default)` never touches the DB at parse time.
# --------------------------------------------------------------------------- #
_REPO = f"{{{{ var.value.get('flight_repo_root', '{DERIVED_REPO_ROOT}') }}}}"
_PY = "{{ var.value.get('flight_python', 'python') }}"
_LAKE = (
    "{{ var.value.get('flight_lake_root', "
    f"var.value.get('flight_repo_root', '{DERIVED_REPO_ROOT}') ~ '/data/lake') }}}}"
)
_DUCKDB = (
    "{{ var.value.get('flight_duckdb_path', "
    "(var.value.get('flight_lake_root', "
    f"var.value.get('flight_repo_root', '{DERIVED_REPO_ROOT}') ~ '/data/lake')) "
    "~ '/gold.duckdb') }}"
)
_YEARS = "{{ var.value.get('flight_train_years', '2022,2023,2024,2025') }}"

# Plain-Python sub-paths derived from the repo template.
_SHARED = f"{_REPO}/shared"
_INGESTION = f"{_REPO}/ingestion"
_LAKEHOUSE = f"{_REPO}/lakehouse"
_ML = f"{_REPO}/ml"
_DBT = f"{_REPO}/dbt/flight"
_ML_ARTIFACTS = f"{_ML}/artifacts"
_PUBLISH = f"{_REPO}/airflow/scripts/publish_artifacts.py"


# --------------------------------------------------------------------------- #
# Non-templated accessors used by PythonOperator callables (which run with a
# live Airflow context, so importing Variable there is fine). Kept as functions
# so the import happens lazily at call time, never at parse.
# --------------------------------------------------------------------------- #
def repo_root() -> str:
    from airflow.models import Variable

    return Variable.get("flight_repo_root", default_var=DERIVED_REPO_ROOT)


def ml_metrics_path() -> str:
    return os.path.join(repo_root(), "ml", "reports", "metrics.json")


def roc_auc_gate() -> float:
    from airflow.models import Variable

    return float(Variable.get("flight_roc_auc_gate", default_var="0.55"))


# --------------------------------------------------------------------------- #
# Bash command builders (return Jinja-templated strings). Each sub-project runs
# from its own dir with PYTHONPATH including shared/ so flight_contracts imports
# even without `pip install -e`.
# --------------------------------------------------------------------------- #
def _env_prefix() -> str:
    return (
        "export PYTHONIOENCODING=utf-8 && "
        f'export PYTHONPATH="{_SHARED}:${{PYTHONPATH:-}}" && '
        f'export LAKE_ROOT="{_LAKE}" && '
        f'export DUCKDB_PATH="{_DUCKDB}"'
    )


def ingest_cmd(target: str, years: str | None = None) -> str:
    """target in {airports, bts, weather, all}. `years` may be a literal or a
    Jinja expression; defaults to the flight_train_years Variable."""
    yr = ""
    if target in {"bts", "weather", "all"}:
        yr = f' --years "{years if years is not None else _YEARS}"'
    return (
        f'{_env_prefix()} && cd "{_INGESTION}" && '
        f'"{_PY}" -m flight_ingest.cli {target}{yr}'
    )


def lakehouse_cmd(stage: str) -> str:
    """stage in {silver, gold, duckdb, all}."""
    return (
        f'{_env_prefix()} && cd "{_LAKEHOUSE}" && '
        f'"{_PY}" -m flight_lakehouse.run --stage {stage}'
    )


def dbt_cmd(action: str) -> str:
    """action in {run, test, ...}."""
    return (
        f'{_env_prefix()} && export DBT_PROFILES_DIR="{_DBT}" && '
        f'cd "{_DBT}" && "{_PY}" -m dbt.cli.main {action}'
    )


def ml_train_cmd(extra: str = "") -> str:
    return (
        f'{_env_prefix()} && cd "{_ML}" && '
        f'"{_PY}" -m flight_ml.pipeline --data "{_DUCKDB}" '
        f'--out "{_ML_ARTIFACTS}"{(" " + extra) if extra else ""}'
    )


def publish_cmd() -> str:
    return (
        f'{_env_prefix()} && export ARTIFACTS_DIR="{_ML_ARTIFACTS}" && '
        f'cd "{_REPO}" && "{_PY}" "{_PUBLISH}" '
        f'--artifacts "{_ML_ARTIFACTS}" --duckdb "{_DUCKDB}"'
    )
