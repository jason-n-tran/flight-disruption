"""Flight Disruption Platform -- main batch + ML pipeline DAG.

End-to-end weekly refresh of the batch ("brain") track:

    [ingest TaskGroup]                lakehouse        dbt          ml         publish
    airports -> bts -> weather  ->  silver -> gold -> run -> test -> train -> publish

This is a WORKING-PC SHOWCASE (see CLAUDE.md "showcase pattern"): it is built to
run and be screenshotted, NOT to be always-on, and the live demo never depends
on it. It orchestrates the real component CLIs via BashOperator.

All paths/years are parameterizable via Airflow Variables -- see ``_config.py``.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.task_group import TaskGroup

import _config as cfg

DEFAULT_ARGS = {
    "owner": "flight-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "execution_timeout": timedelta(hours=3),
}

with DAG(
    dag_id="flight_batch_pipeline",
    description="Weekly batch+ML refresh: ingest -> lakehouse -> dbt -> ml -> publish.",
    default_args=DEFAULT_ARGS,
    schedule="@weekly",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["flight", "batch", "ml", "showcase"],
    params={
        # exposed in the "Trigger DAG w/ config" UI -- edit per run. The default
        # mirrors the flight_train_years Variable / contract span.
        "years": "2022,2023,2024,2025",
    },
) as dag:

    start = EmptyOperator(task_id="start")

    # --- Ingestion (bronze) ------------------------------------------------- #
    with TaskGroup(group_id="ingest", tooltip="OpenFlights -> BTS -> Open-Meteo") as ingest:
        airports = BashOperator(
            task_id="airports",
            bash_command=cfg.ingest_cmd("airports"),
        )
        bts = BashOperator(
            task_id="bts",
            # use the run-config 'years' param, falling back to the Variable default
            bash_command=cfg.ingest_cmd("bts", years="{{ params.years }}"),
        )
        weather = BashOperator(
            task_id="weather",
            bash_command=cfg.ingest_cmd("weather", years="{{ params.years }}"),
        )
        # airports dim must exist before weather (weather iterates the airport dim);
        # bts is independent of airports but ordered for a clean linear story.
        airports >> bts >> weather

    # --- Lakehouse (silver -> gold) ---------------------------------------- #
    silver = BashOperator(
        task_id="lakehouse_silver",
        bash_command=cfg.lakehouse_cmd("silver"),
    )
    gold = BashOperator(
        task_id="lakehouse_gold",
        bash_command=cfg.lakehouse_cmd("gold"),
    )

    # --- dbt (gold marts in DuckDB) ---------------------------------------- #
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=cfg.dbt_cmd("run"),
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=cfg.dbt_cmd("test"),
    )

    # --- ML train ---------------------------------------------------------- #
    ml_train = BashOperator(
        task_id="ml_train",
        bash_command=cfg.ml_train_cmd(),
        execution_timeout=timedelta(hours=2),
    )

    # --- Publish artifacts to object storage (no-op when S3 unset) ---------- #
    publish = BashOperator(
        task_id="publish_artifacts",
        bash_command=cfg.publish_cmd(),
    )

    end = EmptyOperator(task_id="end")

    start >> ingest >> silver >> gold >> dbt_run >> dbt_test >> ml_train >> publish >> end
