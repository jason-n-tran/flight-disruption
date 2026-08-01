"""Flight Disruption Platform -- weather backfill utility DAG.

A small, one-shot-ish utility that backfills the Open-Meteo archive for all
airports. Showcases a DIFFERENT pattern from the main pipeline:

  * ``schedule=None`` -> manual trigger only (a utility, not a cadence).
  * Dynamic task mapping (``BashOperator.expand``) -> one mapped ingest task per
    year, so the backfill fans out and the UI shows per-year progress/retries.

Per project memory: weather backfill is cheap (~1 Open-Meteo call per airport
covers the full range), so this is mostly a demonstrable orchestration pattern.

Working-PC showcase -- manual, not in the live demo critical path.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator

import _config as cfg

DEFAULT_ARGS = {
    "owner": "flight-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=15),
    "execution_timeout": timedelta(hours=1),
}


def _backfill_years() -> list[str]:
    """Years to fan out over -- one dynamically-mapped task each.

    The mapped-task count must be known at PARSE time, so we cannot read an
    Airflow Variable here (that would hit the metadata DB on every parse). We
    read the parse-safe env var FLIGHT_BACKFILL_YEARS (set in .env / compose),
    falling back to the contract span. To backfill a different set, edit the env
    or the literal default and re-trigger.
    """
    raw = os.environ.get("FLIGHT_BACKFILL_YEARS", "2022,2023,2024,2025")
    return [y.strip() for y in raw.split(",") if y.strip()]


with DAG(
    dag_id="flight_weather_backfill",
    description="Manual one-shot weather backfill for all airports (dynamic-mapped per year).",
    default_args=DEFAULT_ARGS,
    schedule=None,  # manual trigger only
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["flight", "weather", "backfill", "utility", "showcase"],
) as dag:

    start = EmptyOperator(task_id="start")

    # airport dim must exist first (weather iterates it).
    ensure_airports = BashOperator(
        task_id="ensure_airports",
        bash_command=cfg.ingest_cmd("airports"),
    )

    # one mapped ingest task per year -> parallel fan-out, per-year retries.
    backfill_per_year = BashOperator.partial(
        task_id="backfill_weather",
    ).expand(
        bash_command=[cfg.ingest_cmd("weather", years=y) for y in _backfill_years()],
    )

    end = EmptyOperator(task_id="end")

    start >> ensure_airports >> backfill_per_year >> end
