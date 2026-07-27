"""FastAPI app — the serving keystone of the Flight Disruption Platform.

On startup it:
  1. resolves artifacts (pulls latest from object storage if ``S3_*`` set, else
     uses the bundled sample) — see ``artifacts_loader``;
  2. loads the native LightGBM bundle (+ SHAP explainer is built lazily on the
     first prediction) via ``flight_ml.artifacts.load_bundle``;
  3. opens the gold DuckDB **read-only**;
  4. lazily wires a Valkey client for live positions (degrades to sample if down).

Every endpoint matches ``shared/flight_contracts/api_contract.md`` exactly.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from flight_ml.artifacts import load_bundle

from .artifacts_loader import ensure_local_artifacts
from .config import get_settings
from .live import LivePositions, airport_congestion
from .predict import predict as run_predict
from .queries import GoldStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("flight_serving.app")


class _State:
    """Holds the loaded singletons (model, gold store, live positions)."""

    settings = None
    artifacts = None
    store: GoldStore | None = None
    live: LivePositions | None = None
    weather_client: httpx.Client | None = None
    model_loaded = False
    gold_loaded = False


state = _State()


# ---------------------------------------------------------------------------
# Request / response models (shapes mirror the api_contract)
# ---------------------------------------------------------------------------
class PredictRequest(BaseModel):
    origin: str = Field(..., min_length=3, max_length=4, examples=["ATL"])
    dest: str = Field(..., min_length=3, max_length=4, examples=["ORD"])
    carrier: str = Field(..., min_length=2, max_length=3, examples=["DL"])
    date: str = Field(..., examples=["2026-06-20"])
    dep_hour: int = Field(..., ge=0, le=23, examples=[17])


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    state.settings = settings

    # 1 + 2. Resolve + load model bundle.
    resolved = ensure_local_artifacts(settings)
    log.info("Artifact source: %s (bundle=%s)", resolved["source"], resolved["bundle_dir"])
    try:
        state.artifacts = load_bundle(resolved["bundle_dir"])
        state.model_loaded = True
        log.info("Loaded model bundle (%d features)", len(state.artifacts.feature_names))
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to load model bundle: %s", exc)
        state.artifacts = None
        state.model_loaded = False

    # 3. Open gold DuckDB read-only.
    try:
        state.store = GoldStore(resolved["duckdb_path"])
        state.gold_loaded = True
        log.info("Opened gold DuckDB read-only at %s", resolved["duckdb_path"])
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to open gold DuckDB: %s", exc)
        state.store = None
        state.gold_loaded = False

    # 4. Live positions (lazy Valkey, sample fallback) + a shared weather client.
    state.live = LivePositions(settings)
    if settings.weather_enabled:
        state.weather_client = httpx.Client(timeout=settings.weather_timeout_seconds)

    yield

    # --- shutdown ---
    if state.store is not None:
        state.store.close()
    if state.live is not None:
        state.live.close()
    if state.weather_client is not None:
        state.weather_client.close()


app = FastAPI(title="Flight Disruption Serving API", version="0.1.0", lifespan=lifespan)


# CORS is configured from env at import time using a fresh settings read so the
# middleware is in place before lifespan runs.
_cors_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_loaded": state.model_loaded,
        "gold_loaded": state.gold_loaded,
        "data_version": state.settings.data_version if state.settings else "unknown",
    }


@app.get("/api/meta/options")
def meta_options() -> dict:
    _require_gold()
    return {
        "airports": state.store.airports(),
        "carriers": state.store.carriers(),
        "example_presets": state.store.example_presets(),
    }


@app.post("/api/predict")
def api_predict(req: PredictRequest) -> dict:
    _require_model()
    _require_gold()
    origin, dest, carrier = req.origin.upper(), req.dest.upper(), req.carrier.upper()
    try:
        return run_predict(
            store=state.store,
            artifacts=state.artifacts,
            origin=origin,
            dest=dest,
            carrier=carrier,
            date_str=req.date,
            dep_hour=req.dep_hour,
            data_version=state.settings.data_version,
            weather_client=state.weather_client,
            weather_enabled=state.settings.weather_enabled,
            weather_timeout=state.settings.weather_timeout_seconds,
        )
    except ValueError as exc:
        # e.g. bad date format
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/live/positions")
def live_positions() -> dict:
    if state.live is None:
        raise HTTPException(status_code=503, detail="live positions not initialized")
    # Signal viewer activity so the streaming producer polls OpenSky (viewer-
    # gated polling). Without this stamp the producer stays idle and the map
    # only ever shows cached/sample data.
    state.live.touch_viewer()
    return state.live.get_positions()


@app.get("/api/airport/{iata}")
def airport(iata: str) -> dict:
    _require_gold()
    iata = iata.upper()
    dim = state.store.airport_dim(iata)
    if dim is None:
        raise HTTPException(status_code=404, detail=f"unknown airport: {iata}")

    historical = state.store.airport_historical(iata)
    positions = state.live.get_positions() if state.live else {"aircraft": []}
    congestion = airport_congestion(positions, dim["lat"], dim["lon"])

    return {
        "iata": dim["iata"],
        "name": dim["name"],
        "lat": dim["lat"],
        "lon": dim["lon"],
        "historical": historical,
        "live_congestion": congestion,
    }
