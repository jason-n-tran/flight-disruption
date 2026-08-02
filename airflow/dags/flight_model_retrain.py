"""Flight Disruption Platform -- monthly model retraining DAG.

Demonstrates the RETRAINING LIFECYCLE with a model-quality gate:

    rebuild_features (gold) -> train -> evaluate
                                          |
                          [BranchPythonOperator: quality gate]
                          /                                   \\
            gate_passed (publish + register)            gate_failed (skip)
                          \\                                   /
                                   join (rejoin)

The gate reads ``ml/reports/metrics.json`` (written by the ml pipeline) and only
proceeds to publish/register if the new model's ROC-AUC beats both:
  * a configurable absolute floor (Variable ``flight_roc_auc_gate``), and
  * the previous model's ROC-AUC, snapshotted to ml/reports/metrics_previous.json.

MLflow registration happens inside the ml pipeline (``flight_ml.registry``) when
MLFLOW_TRACKING_URI / MLFLOW_MODEL_NAME are set; here we surface it as an explicit
"register" step for the showcase narrative.

Working-PC showcase -- not always-on, not in the live demo critical path.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.utils.trigger_rule import TriggerRule

import _config as cfg

DEFAULT_ARGS = {
    "owner": "flight-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "execution_timeout": timedelta(hours=3),
}

TASK_PUBLISH = "gate_passed_publish"
TASK_SKIP = "gate_failed_skip"


def _read_metrics(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
