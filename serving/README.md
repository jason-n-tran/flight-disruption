# serving/ — FastAPI inference + data API

The keystone of the live demo. Two tracks meet here: the **batch/ML brain**
(model bundle + gold DuckDB) and the **live view** (Valkey aircraft cache). The
API serves pre-built artifacts and never depends on Databricks/Kafka/Airflow.

## Endpoints (contract: `shared/flight_contracts/api_contract.md`)

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/health` | liveness + `model_loaded` / `gold_loaded` / `data_version` |
| GET  | `/api/meta/options` | airports + carriers + example presets for the route builder |
| POST | `/api/predict` | calibrated delay probability + risk band + baseline + live SHAP `top_factors` + weather summary |
| GET  | `/api/live/positions` | live aircraft (Valkey → cached → bundled sample; never empty) |
| GET  | `/api/airport/{iata}` | airport bridge: historical reliability + live congestion |
| GET  | `/api/reliability/route?origin=&dest=` | route reliability + per-carrier breakdown |

## How it works

- **Inference is not reinvented.** `/api/predict` builds the `MODEL_FEATURES`
  vector (`flight_serving/predict.py`) and calls the canonical
  `flight_ml.artifacts.predict_proba_one`, which loads the native LightGBM model,
  applies calibration, and runs live SHAP for the signed `top_factors`.
- **Gold marts** are read from DuckDB **read-only** (`flight_serving/queries.py`).
- **Live positions** follow a never-empty fallback chain
  (`flight_serving/live.py`): Valkey `flight:positions:latest` → last good
  in-process snapshot (`cached`) → bundled `data/sample/positions.json`
  (`sample`).
- **Weather** is fetched live from Open-Meteo forecast at serve time
  (`flight_serving/weather.py`); if the date is beyond the horizon or the network
  is unreachable (e.g. this dev machine's SSL proxy), it degrades to
  climatological defaults so `/api/predict` **never fails**.

## Artifact handoff (`flight_serving/artifacts_loader.py`)

On startup, if `S3_*` env vars are set, the API pulls the latest model bundle +
`gold.duckdb` from S3-compatible object storage (MinIO / Backblaze B2) into
`ARTIFACT_CACHE_DIR` and serves from it — this is how the intermittent
Working-PC pipeline ships fresh artifacts without redeploying the API. With no
`S3_*` set, the bundled sample artifacts are used (self-contained, offline).

## Run locally

```bash
pip install -e ../shared -e ../ml -e ../ingestion -e .
python -m pytest -q

# against the real sample artifacts
DUCKDB_PATH=../data/sample/gold.duckdb \
MODEL_PATH=../data/sample/model.lgb \
SAMPLE_DIR=../data/sample \
uvicorn flight_serving.app:app --reload
```

Defaults already point at `../data/sample`, so plain `uvicorn flight_serving.app:app`
also works from this directory.

## Docker

Build context is the **repo root** (so it can copy `shared/`, `ml/`, `ingestion/`
and bake `data/sample/`):

```bash
docker compose up -d serving      # from repo root
```
