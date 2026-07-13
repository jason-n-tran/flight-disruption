# Lake builder image: runs the FULL batch pipeline
#   ingest (Python) -> medallion (PySpark, needs a JVM) -> dbt -> train -> publish
#
# Build context is the REPO ROOT (see root docker-compose `lake-builder`), so we
# COPY everything the pipeline touches. Driven by scripts/run_pipeline.py.
#
#   docker compose -f docker-compose.yml -f infra/docker-compose.workingpc.yml \
#       --profile pipeline up lake-builder
#
# Base: Python 3.11 (required by flight-contracts) + JRE 17 (PySpark 3.5).
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    LAKE_ROOT=/data/lake \
    DUCKDB_PATH=/data/lake/gold.duckdb \
    PYSPARK_PYTHON=python3 \
    PYSPARK_DRIVER_PYTHON=python3

# JRE 17 for PySpark; libgomp1 = OpenMP runtime required by LightGBM (the train
# stage imports lightgbm and dlopen's libgomp.so.1).
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Shared contracts first (path dep used by every component).
COPY shared/ /app/shared/
COPY ingestion/ /app/ingestion/
COPY lakehouse/ /app/lakehouse/
COPY ml/ /app/ml/
COPY dbt/ /app/dbt/
COPY scripts/ /app/scripts/
COPY airflow/scripts/ /app/airflow/scripts/

# Install all pipeline packages editable so the `flight-contracts` path dep
# resolves and the orchestrator can import every stage.
RUN python3 -m pip install --upgrade pip \
 && python3 -m pip install -e /app/shared \
 && python3 -m pip install -e /app/ingestion \
 && python3 -m pip install -e /app/lakehouse \
 && python3 -m pip install -e /app/ml \
 && python3 -m pip install dbt-duckdb boto3

# Default: the full one-shot pipeline. BTS_YEARS / WEATHER_TOP_N (env) tune it;
# S3_* (env) enable the publish step (otherwise it no-ops).
CMD ["sh", "-c", "python3 scripts/run_pipeline.py"]
